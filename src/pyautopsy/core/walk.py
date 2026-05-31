"""The filesystem-walk orchestrator (META-01, D-15/D-18/D-20, REPORT-02).

:func:`run_walk` mirrors :func:`pyautopsy.core.ingest.run_ingest`: it composes the
proven lower tiers into one forensically-sound operation that turns an opened
evidence image into a normalized per-file inventory in the case store. In order:

1. **Resolve the image and re-assert the read-only guard.** The source is opened
   read-only through the byte-layer seam and the mounted-source guard
   (:func:`integrity.assert_source_not_mounted`) is re-asserted (D-05/P1) — the
   walk never mounts or writes the evidence.
2. **Open the case store.** Phase 1's ingest already created it; the walk opens
   the existing ``case.db`` and resolves the evidence source to attach rows to
   (the latest ``evidence_sources`` row when no id is supplied).
3. **Enumerate volumes** through the FS-layer seam
   (:func:`filesystem.enumerate_volumes`) — every allocated volume (D-15), or a
   single bare-FS volume at offset 0.
4. **Per volume**, open the filesystem (:func:`filesystem.open_fs`). On
   ``OSError`` the volume is encrypted/unsupported: record an explicit
   :class:`~pyautopsy.case.models.VolumeLimitation` finding and **continue** —
   never abort the run or emit empty/garbage rows (D-20, PITFALLS Pitfall 6).
   Otherwise :func:`filesystem.walk_fs` yields every entry (including deleted
   ones, D-18) which is mapped to a :class:`~pyautopsy.case.models.FileRow` and
   bulk-inserted inside one :meth:`CaseStore.transaction` (WR-01).
5. **Audit every stage** (``walk.start`` → ``walk.volume`` →
   ``walk.limitation`` → ``walk.end``) with a FAIL event always written *before*
   the exception propagates (CR-03/REPORT-02).

Per allocated regular file the walk additionally computes MD5 + SHA-1 + SHA-256
in a single streaming pass (META-04, D-17) via :func:`integrity.hash_file` and
identifies the file's type by content signature (META-05, D-19) via
:func:`filetype.file_type` — both reading read-only through the seam's
``read_random`` byte-reader closure (never mounting, D-05/P1). Non-regular
entries (directories/symlinks/devices) are never read for content; oversize files
(over ``--max-hash-size``) record null hashes plus a skip reason.

This module is part of the orchestration tier and **does not import pytsk3** — all
native filesystem access lives behind :mod:`pyautopsy.evidence.filesystem` (D-14).
It classifies FAT (for downstream local-time handling) via the seam's pytsk3-free
``FAT_FS_TYPES`` contract.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pyautopsy.audit import AuditLog
from pyautopsy.case import CaseStore
from pyautopsy.case.models import FileRow, VolumeLimitation
from pyautopsy.evidence import filesystem as fs_seam
from pyautopsy.evidence import filetype as filetype_mod
from pyautopsy.evidence import image as image_seam
from pyautopsy.evidence import integrity
from pyautopsy.evidence.filesystem import (
    EXT_FS_TYPES,
    FAT_FS_TYPES,
    NTFS_FS_TYPES,
    FilesystemError,
)
from pyautopsy.evidence.image import ImageOpenError
from pyautopsy.util.timeutil import from_epoch_utc, iso_utc

# A read-only content byte-reader as exposed by the FS seam (D-14): the closure
# the orchestrator hashes/types through, never a native ``File`` object.
ContentReader = Callable[[int, int], bytes]

# Type-identification callable signature, injected so the orchestrator stays
# testable with a fake typer; defaults to the content-signature ``file_type``
# (python-magic, D-19). It is NOT a pytsk3 seam, so importing it here is allowed.
FileTyper = Callable[[ContentReader, int], "str | None"]

__all__ = ["WalkError", "WalkResult", "run_walk"]

# A small, pytsk3-free map from the filesystem type integer to a stable label
# string for the ``files.fs_type`` column. FAT variants collapse to ``"fat"``
# (the local-time class, D-16); ext2/ext3/ext4 collapse to ``"ext"``; NTFS maps
# to ``"ntfs"``; anything else is ``"unknown"`` so a label always exists. The
# membership sets are imported from the FS seam (derived from the pytsk3 enums)
# so they can never drift from the installed binding (CR-02) — never hard-code the
# enum integers here.


def _fs_type_label(fs_ftype: int) -> str:
    """Return a stable, pytsk3-free filesystem-type label for ``fs_ftype``."""
    if fs_ftype in FAT_FS_TYPES:
        return "fat"
    if fs_ftype in NTFS_FS_TYPES:
        return "ntfs"
    if fs_ftype in EXT_FS_TYPES:
        return "ext"
    return "unknown"


# Exact per-fs-type provenance strings for the ``files.timestamp_source`` column
# (D-16). These are the canonical originating-attribute labels for each filesystem
# family and are asserted verbatim by the META-02 tests — do not paraphrase them.
_TIMESTAMP_SOURCE_BY_LABEL: dict[str, str] = {
    "ext": "ext4:inode",
    "ntfs": "ntfs:$STANDARD_INFORMATION",
    "fat": "fat:dir-entry",
}


def _macb_to_utc_iso(
    secs: int, nano: int, *, is_fat: bool, walk_tz: ZoneInfo
) -> str | None:
    """Normalise one raw TSK MACB epoch to a tz-aware UTC ISO-8601 string (D-16).

    A ``0`` epoch means "not recorded" and yields ``None`` — never a fake
    ``1970-01-01`` (PITFALLS Pitfall 3). For FAT the integer is wall-clock time in
    ``walk_tz`` (FAT stores *local* time, PITFALLS Pitfall 2); it is interpreted in
    that zone then converted to UTC. For ext4/NTFS the epoch is already UTC. Every
    value is routed through :func:`iso_utc`, which raises on a naive datetime, so a
    naive/local timestamp is structurally impossible to persist (D-10, threat
    T-2-02-NAIVE). Sub-second ``nano`` is folded onto the datetime when present.

    Args:
        secs: Raw epoch seconds as TSK reports them (``0`` ⇒ not recorded).
        nano: Sub-second nanoseconds for this stamp (``0`` when absent).
        is_fat: Whether the source filesystem is a FAT variant (local-time).
        walk_tz: The IANA zone used to rebase FAT local times.

    Returns:
        An ISO-8601 string ending in ``+00:00``, or ``None`` for a ``0`` epoch.
    """
    if not secs:
        return None
    micro = (nano // 1000) if nano else 0
    if is_fat:
        # FAT stores LOCAL wall-clock time with no embedded zone. TSK reports
        # those wall-clock fields encoded AS-IF they were a UTC epoch — so the
        # integer's UTC rendering reproduces the stored wall-clock components.
        # We recover those naive wall-clock components, then RE-INTERPRET them as
        # being in ``walk_tz`` and convert that instant to true UTC (D-16, threat
        # T-2-02-FAT). ``datetime.fromtimestamp(secs, tz=walk_tz)`` would NOT do
        # this — it treats ``secs`` as a UTC epoch and merely renders it in
        # ``walk_tz``, leaving the absolute instant unchanged (CR-01).
        naive_wall = datetime.fromtimestamp(secs, tz=timezone.utc).replace(
            tzinfo=None
        )
        dt = naive_wall.replace(tzinfo=walk_tz)
    else:
        # ext4/NTFS epochs are already UTC.
        dt = from_epoch_utc(secs)
    if micro:
        dt = dt.replace(microsecond=micro)
    return iso_utc(dt)


def _macb_fields(
    entry: fs_seam.FileEntry, walk_tz: ZoneInfo
) -> tuple[dict[str, str | None], str | None, dict[str, Any]]:
    """Compute normalised MACB columns + provenance + FAT attrs for one entry.

    Returns a triple of:
      * the ``{m,a,c,b}`` → UTC-ISO-or-``None`` mapping for the ``*_utc`` columns,
      * the ``timestamp_source`` provenance string (or ``None`` for meta-less
        entries / unknown filesystems),
      * any extra ``attributes`` to merge (FAT local-time flags only).

    Meta-less entries (no ``meta_addr``) keep null MACB and no provenance.
    """
    if entry.meta_addr is None:
        return ({"m": None, "a": None, "c": None, "b": None}, None, {})

    is_fat = entry.fs_ftype in FAT_FS_TYPES
    label = _fs_type_label(entry.fs_ftype)
    macb = {
        "m": _macb_to_utc_iso(
            entry.mtime, entry.mtime_nano, is_fat=is_fat, walk_tz=walk_tz
        ),
        "a": _macb_to_utc_iso(
            entry.atime, entry.atime_nano, is_fat=is_fat, walk_tz=walk_tz
        ),
        "c": _macb_to_utc_iso(
            entry.ctime, entry.ctime_nano, is_fat=is_fat, walk_tz=walk_tz
        ),
        "b": _macb_to_utc_iso(
            entry.crtime, entry.crtime_nano, is_fat=is_fat, walk_tz=walk_tz
        ),
    }
    timestamp_source = _TIMESTAMP_SOURCE_BY_LABEL.get(label)
    attributes: dict[str, Any] = {}
    if is_fat:
        # FAT stores LOCAL time at second precision: flag the inference and record
        # the assumed zone so the report never overclaims FAT precision (D-16,
        # threat T-2-02-FAT).
        attributes["time_precision"] = "local-time-inferred"
        attributes["assumed_timezone"] = str(walk_tz)
    return (macb, timestamp_source, attributes)


class WalkError(Exception):
    """Raised when the walk cannot proceed for a non-integrity reason.

    Chiefly: the case directory has no ``case.db`` (ingest was never run) or no
    evidence source to attach the inventory to. Integrity / read-only-boundary
    failures surface as :class:`~pyautopsy.evidence.integrity.MountedSourceError`
    or :class:`~pyautopsy.evidence.integrity.IntegrityError` instead.
    """


# (WR-05) The operational exception set the walk legitimately expects: a
# read-only/integrity boundary failure, an unopenable image, an FS-seam failure,
# a case-store/sqlite error, or our own WalkError. These are recorded as a
# ``walk.error`` FAIL and re-raised. Anything OUTSIDE this set is a genuine
# programming bug (KeyError/AttributeError/TypeError/...): it is recorded under a
# DISTINCT ``walk.crashed`` event so the audit trail never conflates a bug with
# an expected operational failure, then re-raised unwrapped (the traceback is
# preserved either way — neither path swallows the exception).
_EXPECTED_WALK_ERRORS: tuple[type[BaseException], ...] = (
    WalkError,
    integrity.MountedSourceError,
    integrity.IntegrityError,
    ImageOpenError,
    FilesystemError,
    OSError,
    sqlite3.Error,
)


@dataclass(frozen=True, slots=True)
class WalkResult:
    """The analytical outcome of a successful walk (reproducible counts only).

    Carries only analytical content — never wall-clock metadata — so the CLI can
    print a deterministic summary (PITFALLS P3).

    Attributes:
        evidence_source_id: The evidence source the inventory was attached to.
        files_inventoried: Total ``files`` rows written.
        deleted_count: How many of those were deleted/unallocated (D-18).
        volumes_walked: How many volumes were successfully walked.
        limitations_recorded: How many D-20 limitation findings were recorded.
    """

    evidence_source_id: int
    files_inventoried: int
    deleted_count: int
    volumes_walked: int
    limitations_recorded: int


def _latest_evidence_source_id(store: CaseStore) -> int:
    """Return the most-recent ``evidence_sources`` id, or raise :class:`WalkError`."""
    row = store.connection.execute(
        "SELECT id FROM evidence_sources ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        raise WalkError(
            "no evidence source in the case; run `pyautopsy ingest` first so the "
            "walk has an evidence_sources row to attach the inventory to"
        )
    return int(row["id"])


# Meta-type labels that are eligible for content hashing/typing. Only a *regular*
# file has byte content: reading a directory/symlink/device through ``read_random``
# returns dirent bytes / nothing — never the content libmagic or a digest should
# see (Pitfall 5, threat T-2-03-NONREG). Anything else is left unhashed/untyped.
_REGULAR = "reg"

# Stable, magic-free type labels for the common non-regular entries so the report
# can render *something* without ever calling libmagic on dirent bytes (RESEARCH
# Open Question 3). Directories/symlinks get a structural label; everything else
# (devices/fifos/sockets/unknown) stays ``None``.
_NONREG_TYPE_LABELS: dict[str, str] = {"dir": "directory", "lnk": "symlink"}


def _content_fields(
    entry: fs_seam.FileEntry,
    *,
    max_hash_size: int | None,
    typer: FileTyper,
) -> tuple[dict[str, str | None], str | None, dict[str, Any]]:
    """Compute hash + content-type columns for one entry (META-04/META-05).

    Returns a triple of:
      * the ``{md5, sha1, sha256}`` → hex-or-``None`` mapping for the hash columns,
      * the ``file_type`` content-signature string (or a structural label / ``None``),
      * any extra ``attributes`` to merge (a ``hash_skipped`` reason only).

    Content work is gated on an allocated *regular* file with a readable content
    closure (``read_random`` is ``None`` for meta-less entries). Non-regular
    entries are never read for content (Pitfall 5): they get null hashes and an
    optional structural type label. For a qualifying regular file the hashing and
    typing both stream read-only through the seam's ``read_random`` closure
    (D-05/P1 — never a mount).
    """
    null_hashes: dict[str, str | None] = {"md5": None, "sha1": None, "sha256": None}

    if entry.meta_type != _REGULAR:
        # Directories/symlinks/devices: never hashed, never magic-typed.
        return (null_hashes, _NONREG_TYPE_LABELS.get(entry.meta_type), {})

    reader = entry.read_random
    if reader is None:
        # A regular entry with no readable content (no meta/data): leave null.
        return (null_hashes, None, {})

    # (D-18) Only hash allocated regular files. A deleted/unallocated regular
    # entry's data may be partly reused; we do not record a hash for it unless its
    # metadata+data are trivially intact (a normal read returns all of size) —
    # hash_file's own short-read→None covers that case, so we still attempt it but
    # only for allocated entries to avoid hashing reclaimed blocks as if intact.
    attributes: dict[str, Any] = {}
    hashes: dict[str, str | None] = dict(null_hashes)
    if entry.allocated:
        # (WR-01) A per-entry content read can raise OSError/IOError — common for
        # a deleted/corrupt entry whose data runs are gone. That MUST NOT abort
        # the whole inventory (D-20 spirit / Pitfall 6): degrade this one entry to
        # null hashes + a ``read_error`` reason and continue the walk. ``OSError``
        # covers ``IOError`` (an alias since Py3.3).
        try:
            digests = integrity.hash_file(
                reader, entry.size, max_size=max_hash_size
            )
        except OSError:
            digests = None
            attributes["hash_skipped"] = "read_error"
        if digests is not None:
            hashes = {
                "md5": digests["md5"],
                "sha1": digests["sha1"],
                "sha256": digests["sha256"],
            }
        elif "hash_skipped" in attributes:
            # A read_error was already recorded above; leave it.
            pass
        elif max_hash_size is not None and entry.size > max_hash_size:
            attributes["hash_skipped"] = "exceeds_max_hash_size"
        else:
            # A short/truncated read returned no digest (no partial digest, D-17).
            attributes["hash_skipped"] = "short_read"

    # Content typing reads only the leading HEAD_BYTES and is independent of the
    # hash skip, so a file too big to hash can still be typed (head bytes only).
    # (WR-01) Guard the typing read the same way: a read failure degrades to a
    # null type rather than aborting the walk.
    try:
        file_type = typer(reader, entry.size)
    except OSError:
        file_type = None
        # Record a read_error if hashing did not already flag one.
        attributes.setdefault("hash_skipped", "read_error")

    # (WR-02) Typing a deleted/unallocated regular file is still useful, but its
    # blocks may have been reused by another file (D-18: status only, no recovery
    # claims). Flag the provenance so the report never presents the type of a
    # reclaimed-block deleted file as equivalent to an allocated-file type.
    if file_type is not None and not entry.allocated:
        attributes["file_type_provenance"] = "unallocated-blocks-may-be-reused"

    return (hashes, file_type, attributes)


def _build_file_row(
    entry: fs_seam.FileEntry,
    evidence_source_id: int,
    walk_tz: ZoneInfo,
    *,
    max_hash_size: int | None,
    typer: FileTyper,
) -> FileRow:
    """Map a seam :class:`FileEntry` to a persisted :class:`FileRow` (META-01..05).

    Populates the META-01 spine (path/name/addr/status + volume tagging +
    meta-type + fs-type), the META-02 MACB columns (normalised to tz-aware UTC
    ISO-8601 with FAT local-time handling + zero→None, D-16) plus
    ``timestamp_source``, the META-03 ownership/mode columns straight from the
    seam's plain-int ``uid``/``gid``/``mode`` fields (``None`` preserved for
    meta-less entries — never coerced to ``0``), and the META-04/META-05 hash +
    content-type columns for allocated regular files (null for non-regular /
    oversize entries, with a ``hash_skipped`` reason recorded in ``attributes``).
    """
    macb, timestamp_source, attributes = _macb_fields(entry, walk_tz)
    hashes, file_type, hash_attrs = _content_fields(
        entry, max_hash_size=max_hash_size, typer=typer
    )
    # Merge the FAT local-time flags (from MACB) with any hash-skip reason.
    attributes = {**attributes, **hash_attrs}
    return FileRow(
        evidence_source_id=evidence_source_id,
        volume_id=entry.volume_id,
        volume_offset=entry.volume_offset,
        path=entry.path,
        name=entry.name,
        parent_addr=entry.parent_addr,
        meta_addr=entry.meta_addr,
        fs_type=_fs_type_label(entry.fs_ftype),
        size=entry.size,
        allocated=entry.allocated,
        meta_type=entry.meta_type,
        uid=entry.uid,
        gid=entry.gid,
        mode=entry.mode,
        md5=hashes["md5"],
        sha1=hashes["sha1"],
        sha256=hashes["sha256"],
        mtime_utc=macb["m"],
        atime_utc=macb["a"],
        ctime_utc=macb["c"],
        crtime_utc=macb["b"],
        timestamp_source=timestamp_source,
        file_type=file_type,
        attributes=attributes,
    )


def run_walk(
    image: str | os.PathLike[str],
    case_dir: str | os.PathLike[str],
    *,
    evidence_source_id: int | None = None,
    timezone: str = "UTC",
    max_hash_size: int | None = None,
    typer: FileTyper | None = None,
) -> WalkResult:
    """Walk a filesystem image into a normalized ``files`` inventory (META-01).

    See the module docstring for the full ordered pipeline. The source is opened
    read-only and never mounted; every entry (including deleted ones) is
    inventoried with allocated/unallocated status + inode/MFT address + volume
    tagging (D-15/D-18), and any encrypted/unsupported volume is recorded as a
    D-20 limitation while the walk continues.

    Args:
        image: Path to the evidence image (raw/dd file or first E01 segment).
        case_dir: Existing case directory (created by a prior ingest).
        evidence_source_id: Which evidence source to attach the inventory to;
            defaults to the latest ``evidence_sources`` row in the case.
        timezone: IANA zone name used for FAT local-time handling downstream
            (validated by the caller); recorded for provenance.
        max_hash_size: Skip hashing any file whose logical size exceeds this many
            bytes (records null hashes + a ``hash_skipped`` reason); ``None``
            (default) means no cap (META-04/D-17, threat T-2-03-HOG).
        typer: Content-signature type-identification callable, injected for
            testability; defaults to :func:`filetype.file_type` (python-magic,
            META-05/D-19).

    Returns:
        A :class:`WalkResult` with the analytical inventory counts.

    Raises:
        WalkError: If the case has no ``case.db`` or no evidence source.
        MountedSourceError: If the source path is a mounted filesystem (P1).
        ImageOpenError: If the image cannot be opened read-only.
    """
    image_path = Path(image).resolve()
    case_path = Path(case_dir).resolve()

    # Default to the content-signature typer (python-magic); injectable for tests.
    active_typer: FileTyper = typer if typer is not None else filetype_mod.file_type

    # Resolve the FAT local-time zone once (validated here; a bad zone raises
    # before any evidence access — threat T-2-02-TZ / Security V5).
    walk_tz = ZoneInfo(timezone)

    # (1) Re-assert the read-only / not-mounted guard before any access (D-05/P1).
    integrity.assert_source_not_mounted(image_path)

    # (2) Open the existing case store (ingest created it in Phase 1).
    try:
        store = CaseStore.open(case_path)
    except FileNotFoundError as exc:
        raise WalkError(
            f"no case database under {case_path}; run `pyautopsy ingest` first"
        ) from exc

    audit = AuditLog(case_path)
    audit.write(
        "walk.start",
        image=str(image_path),
        case_dir=str(case_path),
        timezone=timezone,
        max_hash_size=max_hash_size,
    )

    files_inventoried = 0
    deleted_count = 0
    volumes_walked = 0
    limitations_recorded = 0

    try:
        source_id = (
            evidence_source_id
            if evidence_source_id is not None
            else _latest_evidence_source_id(store)
        )

        handle = image_seam.open_image(image_path)
        try:
            # (WR-02) Re-assert not-mounted after the open, before reading.
            integrity.assert_source_not_mounted(image_path)

            with store.transaction():
                for vol in fs_seam.enumerate_volumes(handle.image):
                    audit.write(
                        "walk.volume",
                        volume_id=vol.volume_id,
                        volume_offset=vol.offset,
                        description=vol.description,
                    )
                    try:
                        fs = fs_seam.open_fs(handle.image, vol.offset)
                    except OSError as exc:
                        # (D-20) Encrypted/unsupported volume: record a finding
                        # and continue — never abort, never emit garbage rows.
                        attributes = _encryption_hint(handle, vol.offset)
                        store.insert_volume_limitation(
                            VolumeLimitation(
                                evidence_source_id=source_id,
                                volume_id=vol.volume_id,
                                volume_offset=vol.offset,
                                detected_desc=vol.description,
                                reason=str(exc),
                                attributes=attributes,
                            )
                        )
                        limitations_recorded += 1
                        audit.write(
                            "walk.limitation",
                            volume_id=vol.volume_id,
                            volume_offset=vol.offset,
                            reason=str(exc),
                        )
                        continue

                    rows: list[FileRow] = []
                    vol_deleted = 0
                    for entry in fs_seam.walk_fs(fs, vol.volume_id, vol.offset):
                        rows.append(
                            _build_file_row(
                                entry,
                                source_id,
                                walk_tz,
                                max_hash_size=max_hash_size,
                                typer=active_typer,
                            )
                        )
                        if entry.allocated is False:
                            vol_deleted += 1
                    store.insert_files(rows)
                    files_inventoried += len(rows)
                    deleted_count += vol_deleted
                    volumes_walked += 1
                    audit.write(
                        "walk.volume_done",
                        volume_id=vol.volume_id,
                        files=len(rows),
                        deleted=vol_deleted,
                    )
        finally:
            handle.close()

        audit.write(
            "walk.end",
            outcome="SUCCESS",
            evidence_source_id=source_id,
            files_inventoried=files_inventoried,
            deleted_count=deleted_count,
            volumes_walked=volumes_walked,
            limitations_recorded=limitations_recorded,
        )
    except _EXPECTED_WALK_ERRORS as exc:
        # (CR-03/WR-05) An EXPECTED operational failure: always leave a terminal
        # FAIL event before propagating, then re-raise (traceback preserved).
        audit.write(
            "walk.error",
            outcome="FAIL",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise
    except Exception as exc:
        # (WR-05) An UNEXPECTED error — a genuine programming bug, not an
        # operational failure. Record it under a DISTINCT ``walk.crashed`` event
        # (so the audit trail never conflates a bug with an expected failure),
        # then re-raise unwrapped so the bug surfaces with its full traceback.
        audit.write(
            "walk.crashed",
            outcome="FAIL",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise
    finally:
        store.close()

    return WalkResult(
        evidence_source_id=source_id,
        files_inventoried=files_inventoried,
        deleted_count=deleted_count,
        volumes_walked=volumes_walked,
        limitations_recorded=limitations_recorded,
    )


# Cheap, optional encryption-container hints (02-RESEARCH Pattern 7/A2). Read the
# first bytes at the volume offset read-only and label a likely LUKS/BitLocker
# container so the D-20 finding is more informative. Never attempts decryption.
_LUKS_MAGIC = b"LUKS\xba\xbe"
_BITLOCKER_MARKER = b"-FVE-FS-"


def _encryption_hint(
    handle: image_seam.ImageHandle, offset: int
) -> dict[str, str]:
    """Return an optional ``{"encryption_hint": ...}`` for a D-20 finding.

    Reads the first 512 bytes at ``offset`` (read-only) and checks well-known
    container magic. Any read failure is swallowed — the hint is best-effort and
    must never break the D-20 continue-the-walk contract.
    """
    try:
        head = handle.read(offset, 512)
    except OSError:
        return {}
    if head.startswith(_LUKS_MAGIC):
        return {"encryption_hint": "likely LUKS"}
    if _BITLOCKER_MARKER in head[:16]:
        return {"encryption_hint": "likely BitLocker"}
    return {}
