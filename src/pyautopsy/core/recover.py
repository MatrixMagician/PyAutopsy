"""The deleted/orphan-file recovery orchestrator (RECOV-01/02/03, D-29..D-42).

:func:`run_recover` is the sibling of :func:`pyautopsy.core.walk.run_walk`: it
composes the proven lower tiers into one forensically-sound operation that turns
the Phase-2 deleted-entry inventory into recovered file *content* — written to a
confined ``recovered/`` tree, hashed, classified by an honest confidence tier,
and cataloged as ``files`` rows. In order:

1. **Re-assert the read-only guard.** :func:`integrity.assert_source_not_mounted`
   is re-asserted before any access (D-42/D-05/P1) — recovery never mounts or
   writes the evidence; only the case dir's ``recovered/`` tree + ``case.db`` are
   written.
2. **Open the case store** (ingest + walk already created it) and resolve the
   evidence source to attach recovered rows to.
3. **Per volume**, enumerate the filesystem entries through the FS seam
   (:func:`filesystem.walk_fs`) and derive the allocated-block set once
   (:func:`filesystem.allocated_data_blocks`), then for each deleted (``allocated
   is False``) entry reopen the inode via
   :func:`filesystem.recover_meta`, re-check the Pitfall-5 reallocation hazard,
   classify the tier (:func:`classify_tier`), write the recovered bytes through
   the :mod:`pyautopsy.util.confine` path-confinement helpers with a
   deterministic ``vol/off/meta_addr`` name (D-33/D-34), hash the written bytes via
   :func:`integrity.hash_file` (single pass, D-37), and build a recovered
   :class:`~pyautopsy.case.models.FileRow` (``allocated=False``, ``recovered=1``).
4. **Catalog** all recovered rows via :meth:`CaseStore.insert_recovered_files`
   inside one :meth:`CaseStore.transaction` (sole-writer + atomic, WR-01/D-08).
5. **Audit every stage** with a FAIL event always written *before* the exception
   propagates (the two-arm expected-vs-crashed pattern).

This module is part of the orchestration tier and **does not import pytsk3** —
ALL native filesystem access (inode reopen, run enumeration, the derived
allocated-block set) lives behind :mod:`pyautopsy.evidence.filesystem` (D-14).

Confidence labels here describe **data survival only** — never user intent or a
good/bad verdict (D-32, mirrors the Phase-3 WR-02 honesty discipline). The
report copy this module exposes (:data:`RECOVERY_REPORT_COPY`) is honesty-scanned
by the recovery tests.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pyautopsy.audit import AuditLog
from pyautopsy.case import CaseStore
from pyautopsy.case.models import FileRow
from pyautopsy.core.epilogue import audited_step
from pyautopsy.errors import PyAutopsyError
from pyautopsy.evidence import filesystem as fs_seam
from pyautopsy.evidence import filetype as filetype_mod
from pyautopsy.evidence import image as image_seam
from pyautopsy.evidence import integrity
from pyautopsy.evidence.filesystem import (
    EXT_FS_TYPES,
    FAT_FS_TYPES,
    NTFS_FS_TYPES,
)
from pyautopsy.util.confine import confined_target, sanitize_name

__all__ = [
    "RECOVERY_REPORT_COPY",
    "RecoverError",
    "RecoverResult",
    "RecoveredFile",
    "classify_tier",
    "run_recover",
]

# A read-only content byte-reader as exposed by the FS seam (D-14).
ContentReader = Callable[[int, int], bytes]
FileTyper = Callable[[ContentReader, int], "str | None"]

# Tier label constants — the current two-tier domain (D-30). Free-form strings so
# a future ``journal``/``carved`` tier is just a new value, no schema churn.
_TIER_INTACT = "intact"
_TIER_OVERWRITTEN = "partial/overwritten"


def _fs_type_label(fs_ftype: int) -> str:
    """Return a stable, pytsk3-free filesystem-type label (mirrors walk.py).

    The membership sets are the seam's pytsk3-free frozensets derived from the
    installed binding's enums (CR-02), so the labels never drift.
    """
    if fs_ftype in FAT_FS_TYPES:
        return "fat"
    if fs_ftype in NTFS_FS_TYPES:
        return "ntfs"
    if fs_ftype in EXT_FS_TYPES:
        return "ext"
    return "unknown"


# Honesty-reviewed, human-facing copy the report's recovery sections render
# (D-32, mirrors assemble.py's integrity copy and the Phase-3 WR-02 test). Every
# string describes DATA SURVIVAL only — it must never assert intent or a
# good/bad verdict. ``test_no_overclaiming_copy`` scans this blob for a forbidden
# substring set, so keep the wording strictly survival-oriented.
RECOVERY_REPORT_COPY: dict[str, str] = {
    "section_intro": (
        "Recovered Files lists deleted and orphan entries whose metadata and "
        "data survived enough to read their content back. A confidence tier "
        "describes only how much of the on-disk data survived — it makes no "
        "claim about who removed an entry or why, and is not a judgement of the "
        "content."
    ),
    "tier_intact": (
        "intact — every surviving data block still belongs to this entry; no "
        "block was observed reallocated to an allocated file. Data survival "
        "only; this is not a guarantee the content is unmodified."
    ),
    "tier_partial_overwritten": (
        "partial/overwritten — one or more of this entry's former data blocks "
        "are no longer recoverable for it (reallocated to an allocated file, or "
        "its block pointers were cleared on unlink). Recovered bytes may be "
        "incomplete or mixed with another entry's data."
    ),
    "caveat_ntfs_resident": (
        "Resident data recovered from the MFT record (the entry was small enough "
        "to be stored inside its metadata record, so it has no separate data "
        "blocks)."
    ),
    "caveat_ext4_pointers_cleared": (
        "ext4 clears an inode's block pointers on unlink, so most deleted ext4 "
        "entries expose no recoverable data runs; signature carving (a later "
        "capability) is the path for those."
    ),
    "caveat_fat_first_char_lost": (
        "FAT zeroes the first character of a deleted name, so a recovered FAT "
        "name is lossy and is not treated as authoritative."
    ),
    "orphan_intro": (
        "Orphan Files are deleted entries whose parent directory is itself gone, "
        "so they have no path back to the root. They are listed separately; "
        "orphan status is a provenance fact, independent of the confidence tier."
    ),
}


def classify_tier(
    entry: Any, allocated_blocks: frozenset[int]
) -> tuple[str, dict[str, Any]]:
    """Classify a recovered entry's confidence tier from its block survival.

    Pure logic over the seam's plain-int outputs (no pytsk3) so it is unit-
    testable with fakes (mirrors ``walk._content_fields``). Returns the tier
    string plus a rationale dict for the row ``attributes`` — the rationale
    describes DATA SURVIVAL ONLY, never intent (D-32). Decision order
    (RESEARCH §Code Example):

    1. ``now_allocated`` — the reopened inode was reallocated to a live file
       (Pitfall 5) ⇒ ``partial/overwritten`` (never present a live file's bytes
       as the deleted entry's content).
    2. No data runs but resident data survives (NTFS small file, Pitfall 3) ⇒
       ``intact`` with the resident-from-MFT caveat.
    3. No data runs but a non-zero size (ext4 zeroed pointers, Pitfall 2) ⇒
       ``partial/overwritten`` with the pointers-cleared caveat.
    4. Any data block overlaps an allocated file's blocks ⇒ ``partial/
       overwritten`` with the overlapping blocks recorded.
    5. Otherwise every surviving block is still unallocated ⇒ ``intact``.

    Args:
        entry: A :class:`~pyautopsy.evidence.filesystem.RecoveredEntry` (or a fake
            with the same ``data_blocks``/``has_resident_data``/``now_allocated``/
            ``size`` attributes).
        allocated_blocks: The derived set of blocks owned by allocated files.

    Returns:
        ``(tier, rationale)`` — the tier string and a JSON-serialisable rationale.
    """
    if entry.now_allocated:
        return _TIER_OVERWRITTEN, {
            "reason": "inode reallocated to a live file at recover time",
        }
    data_blocks = tuple(entry.data_blocks)
    if not data_blocks and entry.has_resident_data:
        return _TIER_INTACT, {
            "reason": "resident data recovered from the MFT record",
            "caveat": RECOVERY_REPORT_COPY["caveat_ntfs_resident"],
        }
    if not data_blocks and entry.size > 0:
        return _TIER_OVERWRITTEN, {
            "reason": "no recoverable data runs (block pointers cleared on unlink)",
            "caveat": RECOVERY_REPORT_COPY["caveat_ext4_pointers_cleared"],
        }
    overlap = sorted(set(data_blocks) & allocated_blocks)
    if overlap:
        return _TIER_OVERWRITTEN, {
            "reason": "data blocks reallocated to an allocated file",
            "overlapping_blocks": overlap[:32],
        }
    return _TIER_INTACT, {"reason": "all surviving data blocks still unallocated"}


@dataclass(frozen=True, slots=True)
class RecoveredFile:
    """A reproducible descriptor of one recovered entry (no wall-clock).

    Exposed on :class:`RecoverResult` so the CLI/report can list recovered vs
    orphan entries separately (RECOV-02) without re-reading the store.

    Attributes:
        meta_addr: The recovered entry's inode/MFT address.
        path: The entry's original filesystem path (evidence reference).
        confidence_tier: ``intact`` or ``partial/overwritten`` (D-30).
        is_orphan: Whether the entry's parent directory is gone (RECOV-02).
        recovered_path: Case-relative path the recovered bytes were written to.
    """

    meta_addr: int
    path: str
    confidence_tier: str
    is_orphan: bool
    recovered_path: str | None


@dataclass(frozen=True, slots=True)
class RecoverResult:
    """The analytical outcome of a recovery run (reproducible counts only).

    Carries only analytical content — never wall-clock — so the CLI prints a
    deterministic summary and the reproducibility test can compare two runs.
    ``recovered`` and ``orphans`` are DISTINCT lists (RECOV-02/D-25): an orphan
    entry appears only in ``orphans``, never in ``recovered``.

    Attributes:
        evidence_source_id: The evidence source the recovered rows attached to.
        files_recovered: Total recovered rows written (normal + orphan).
        intact_count: How many were classified ``intact``.
        overwritten_count: How many were classified ``partial/overwritten``.
        orphan_count: How many were orphans (``len(orphans)``).
        recovered: Non-orphan recovered entries (the normal recovered list).
        orphans: Orphan recovered entries (the separate orphan list).
    """

    evidence_source_id: int
    files_recovered: int
    intact_count: int
    overwritten_count: int
    orphan_count: int
    recovered: tuple[RecoveredFile, ...] = field(default_factory=tuple)
    orphans: tuple[RecoveredFile, ...] = field(default_factory=tuple)


class RecoverError(PyAutopsyError):
    """Raised when recovery cannot proceed for a non-integrity reason.

    Chiefly: the case directory has no ``case.db`` (ingest/walk was never run) or
    no evidence source to attach recovered rows to. Integrity / read-only-boundary
    failures surface as :class:`~pyautopsy.evidence.integrity.MountedSourceError`
    or :class:`~pyautopsy.evidence.integrity.IntegrityError` instead.
    """


def _latest_evidence_source_id(store: CaseStore) -> int:
    """Return the latest ``evidence_sources`` id, or raise :class:`RecoverError`.

    Reads through the CaseStore (WR-02: no raw SQL outside the store boundary).
    """
    source_id = store.get_latest_evidence_source_id()
    if source_id is None:
        raise RecoverError(
            "no evidence source in the case; run `pyautopsy ingest` + `walk` "
            "first so recovery has an inventory to recover from"
        )
    return source_id


def _recovered_target(
    case_path: Path, volume_id: int, volume_offset: int, meta_addr: int, name: str
) -> tuple[Path, str]:
    """Resolve the confined, deterministic write path for a recovered entry.

    Routes through the :mod:`pyautopsy.util.confine` helpers (``sanitize_name``
    + ``confined_target`` realpath confinement, D-33) with a deterministic name
    keyed by ``vol<id>-off<off>/<meta_addr>-<safe_name>`` (D-34) — NEVER the raw
    deleted filename (which is adversarial: it may contain ``../``, control
    chars, FAT ``?``/``_``). The deterministic key makes recovered names
    collision-safe and reproducible across runs (CLI-02/Pitfall 6).

    Returns:
        ``(absolute_target, case_relative_path)``.
    """
    dest = (case_path / "recovered" / f"vol{volume_id}-off{volume_offset}").resolve()
    dest.mkdir(parents=True, exist_ok=True)
    safe_name = sanitize_name(name) or "unnamed"
    rel = f"{meta_addr}-{safe_name}"
    dest_real = os.path.realpath(dest)
    target = Path(confined_target(dest_real, rel))
    case_relative = os.path.relpath(target, case_path)
    return target, case_relative


def _write_recovered_bytes(
    target: Path, read_random: ContentReader, size: int, *, max_hash_size: int | None
) -> None:
    """Stream the recovered content to ``target`` (read-only over the seam).

    Honors ``max_hash_size`` as a write cap too (a size-bomb guard against
    crafted recovered content, T-04-01-BOMB): a logical size over the cap is
    not written. The source is never written — only the case-dir target.
    """
    if max_hash_size is not None and size > max_hash_size:
        # Size bomb guard: do not materialise an oversize recovered blob.
        target.write_bytes(b"")
        return
    chunk = 1 * 1024 * 1024
    off = 0
    with open(target, "wb") as out:
        while off < size:
            want = min(chunk, size - off)
            block = read_random(off, want)
            if not block:
                break
            out.write(block)
            off += len(block)


def run_recover(
    image: str | os.PathLike[str],
    case_dir: str | os.PathLike[str],
    *,
    evidence_source_id: int | None = None,
    max_hash_size: int | None = None,
    typer: FileTyper | None = None,
) -> RecoverResult:
    """Recover deleted/orphan file content into a confined ``recovered/`` tree.

    See the module docstring for the full ordered pipeline. The source is opened
    read-only and never mounted or written (D-42); recovered bytes land only
    under ``<case_dir>/recovered/`` with deterministic, confined names (D-33/D-34)
    and are cataloged as ``files`` rows (``allocated=False``, ``recovered=1``)
    via CaseStore (sole writer, D-08). Each recovered entry carries an honest
    confidence tier describing data survival only (D-32).

    Args:
        image: Path to the evidence image (raw/dd file or first E01 segment).
        case_dir: Existing case directory (created by a prior ingest + walk).
        evidence_source_id: Which evidence source to recover from; defaults to the
            latest ``evidence_sources`` row in the case.
        max_hash_size: Skip hashing (and writing) any entry whose logical size
            exceeds this many bytes — the recovered-content size-bomb guard
            (T-04-01-BOMB); ``None`` (default) means no cap.
        typer: Content-signature type-identification callable, injected for
            testability; defaults to :func:`filetype.file_type`.

    Returns:
        A :class:`RecoverResult` with reproducible recovery counts and the
        separate recovered/orphan lists (RECOV-02).

    Raises:
        RecoverError: If the case has no ``case.db`` or no evidence source.
        MountedSourceError: If the source path is a mounted filesystem (P1).
        ImageOpenError: If the image cannot be opened read-only.
    """
    image_path = Path(image).resolve()
    case_path = Path(case_dir).resolve()
    active_typer: FileTyper = typer if typer is not None else filetype_mod.file_type

    # (1) Re-assert the read-only / not-mounted guard before any access (D-42).
    integrity.assert_source_not_mounted(image_path)

    # (2) Open the existing case store (ingest + walk created it).
    try:
        store = CaseStore.open(case_path)
    except FileNotFoundError as exc:
        raise RecoverError(
            f"no case database under {case_path}; run `pyautopsy ingest` first"
        ) from exc

    audit = AuditLog(case_path)
    audit.write(
        "recover.start",
        image=str(image_path),
        case_dir=str(case_path),
        max_hash_size=max_hash_size,
    )

    recovered_list: list[RecoveredFile] = []
    orphan_list: list[RecoveredFile] = []
    intact_count = 0
    overwritten_count = 0

    with audited_step(audit, store, "recover", RecoverError):
        source_id = (
            evidence_source_id
            if evidence_source_id is not None
            else _latest_evidence_source_id(store)
        )

        handle = image_seam.open_image(image_path)
        try:
            # (D-42) Re-assert not-mounted after the open, before reading.
            integrity.assert_source_not_mounted(image_path)

            recovered_rows: list[FileRow] = []
            # Enumerate volumes via the seam; recovery runs standalone (it does
            # not require a prior walk inventory). Deleted entries (allocated is
            # False) are the recovery candidates; only entries the FS already
            # classified deleted are recovered (Pitfall 5 re-check below).
            for vol in fs_seam.enumerate_volumes(handle.image):
                volume_id = vol.volume_id
                volume_offset = vol.offset
                try:
                    fs = fs_seam.open_fs(handle.image, volume_offset)
                except OSError:
                    # Encrypted/unsupported volume: nothing to recover here.
                    continue
                allocated_blocks = fs_seam.allocated_data_blocks(fs)
                fs_type_label = _fs_type_label(fs_seam.fs_type_int(fs))

                # Deleted recoverable regular inodes (seam-derived, ascending
                # meta_addr order — deterministic, Pitfall 6). The seam unions a
                # directory walk (name/path/parent for surviving dir links) with
                # an inode-range scan (broken-link inodes, e.g. NTFS resident).
                for di in fs_seam.iter_deleted_inodes(fs, volume_id, volume_offset):
                    entry = fs_seam.recover_meta(fs, di.meta_addr)
                    if entry is None:
                        continue

                    tier, rationale = classify_tier(entry, allocated_blocks)
                    # Orphan-ness is a provenance fact from directory structure
                    # (parent gone), unioned with the TSK ORPHAN meta flag.
                    is_orphan = di.is_orphan or entry.is_orphan
                    target, rel_path = _recovered_target(
                        case_path, volume_id, volume_offset, entry.meta_addr, di.name
                    )

                    attributes: dict[str, Any] = {
                        "recovery_tier_rationale": rationale,
                    }
                    md5 = sha1 = sha256 = None
                    file_type = None
                    if entry.read_random is not None and entry.size:
                        reader = entry.read_random
                        _write_recovered_bytes(
                            target, reader, entry.size, max_hash_size=max_hash_size
                        )
                        try:
                            digests = integrity.hash_file(
                                reader, entry.size, max_size=max_hash_size
                            )
                        except OSError:
                            digests = None
                            attributes["hash_skipped"] = "read_error"
                        if digests is not None:
                            md5 = digests["md5"]
                            sha1 = digests["sha1"]
                            sha256 = digests["sha256"]
                        elif max_hash_size is not None and entry.size > max_hash_size:
                            attributes["hash_skipped"] = "exceeds_max_hash_size"
                        # WR-04: gate content typing behind the SAME size cap as
                        # hashing. active_typer streams the full content through
                        # the sniffer, so typing an oversize entry re-opens the
                        # exact size-bomb surface (T-04-01-BOMB) the cap is meant
                        # to bound. Only type when within the cap; file_type stays
                        # None otherwise (deterministic — same input, same skip).
                        if max_hash_size is None or entry.size <= max_hash_size:
                            try:
                                file_type = active_typer(reader, entry.size)
                            except OSError:
                                file_type = None
                    else:
                        # Nothing to read (ext4 zeroed pointers / no data): write
                        # an empty placeholder so the recovered/ row has a file.
                        target.write_bytes(b"")

                    recovered_rows.append(
                        FileRow(
                            evidence_source_id=source_id,
                            volume_id=volume_id,
                            volume_offset=volume_offset,
                            path=di.path,
                            name=di.name,
                            parent_addr=di.parent_addr,
                            meta_addr=entry.meta_addr,
                            fs_type=fs_type_label,
                            size=entry.size,
                            allocated=False,
                            meta_type=entry.meta_type,
                            md5=md5,
                            sha1=sha1,
                            sha256=sha256,
                            file_type=file_type,
                            recovered=True,
                            confidence_tier=tier,
                            recovered_path=rel_path,
                            is_orphan=is_orphan,
                            attributes=attributes,
                        )
                    )

                    descriptor = RecoveredFile(
                        meta_addr=entry.meta_addr,
                        path=di.path,
                        confidence_tier=tier,
                        is_orphan=is_orphan,
                        recovered_path=rel_path,
                    )
                    if is_orphan:
                        orphan_list.append(descriptor)
                    else:
                        recovered_list.append(descriptor)
                    if tier == _TIER_INTACT:
                        intact_count += 1
                    else:
                        overwritten_count += 1

            with store.transaction():
                store.insert_recovered_files(recovered_rows)
                # Record that recovery covered this case, so the report can
                # state its own coverage from the case data (D-40 honesty).
                store.record_stage(
                    store.get_evidence_source(source_id).case_id, "recover"
                )
        finally:
            handle.close()

        files_recovered = len(recovered_list) + len(orphan_list)
        audit.write(
            "recover.end",
            outcome="SUCCESS",
            evidence_source_id=source_id,
            files_recovered=files_recovered,
            intact_count=intact_count,
            overwritten_count=overwritten_count,
            orphan_count=len(orphan_list),
        )

    return RecoverResult(
        evidence_source_id=source_id,
        files_recovered=len(recovered_list) + len(orphan_list),
        intact_count=intact_count,
        overwritten_count=overwritten_count,
        orphan_count=len(orphan_list),
        recovered=tuple(recovered_list),
        orphans=tuple(orphan_list),
    )
