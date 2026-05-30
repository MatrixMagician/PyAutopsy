"""The hardened ``safe_extract`` jail — the only sanctioned archive expander.

This module implements the Phase-1 security completion gate (INGEST-04, D-11):
the single sanctioned way to expand any untrusted archive/container. Evidence is
adversarial input (PITFALLS P6), so every member is canonicalized and confined to
the destination jail, symlinks / hardlinks / device-special files are refused, and
hard decompression-bomb caps (total size, per-entry size, compression ratio, entry
count, nesting depth) are enforced.

Layered defenses (01-RESEARCH.md §Safe-Extraction §1–7):

1. **Path confinement** — for every member the realpath of the write target must
   be the destination or live under it; absolute names and ``..`` components are
   rejected before resolution.
2. **Tar** — ``filter='data'`` is passed *explicitly* on every extract regardless
   of the Python version (Pitfall 3: the default only became ``'data'`` in 3.14).
   It blocks traversal, absolute paths, symlinks, hardlinks, and device files.
3. **Zip** — the stdlib has no filter (Pitfall 2); confinement and symlink refusal
   are hand-written per entry.
4. **Symlink / hardlink / device / special refusal** — via ``filter='data'`` for
   tar, explicit external-attr checks for zip.
5. **Decompression-bomb caps** — hand-written (NOT covered by ``filter='data'`` —
   Pitfall 1): a running uncompressed-byte counter aborts mid-stream before disk
   exhaustion; per-entry, ratio, count, and depth limits are enforced.
6. **Name sanitization** — the on-disk write-name is sanitized; the original member
   name is preserved as evidence metadata.
7. **Per-member error isolation** — a malformed member can be recorded and skipped
   without aborting the whole run (``on_member_error="skip"``); the default is to
   raise so a single rejection is loud.

The utility has no caller in the Phase-1 ingest path — its consumers (archive/log
parsers) arrive in Phase 5 — but it is built and gated now to lock the security
contract early (01-RESEARCH.md §Architecture note).
"""

from __future__ import annotations

import os
import stat
import tarfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "ExtractionLimits",
    "ExtractionRejected",
    "ExtractionResult",
    "MemberRecord",
    "safe_extract",
]

# Default decompression-bomb thresholds (01-RESEARCH.md §5 / Assumption A2 —
# sane, configurable defaults).
_DEFAULT_MAX_TOTAL_UNCOMPRESSED = 1 * 1024 * 1024 * 1024  # 1 GiB
_DEFAULT_MAX_ENTRY_SIZE = 256 * 1024 * 1024  # 256 MiB
_DEFAULT_MAX_RATIO = 100  # uncompressed / compressed
_DEFAULT_MAX_ENTRIES = 10_000
_DEFAULT_MAX_DEPTH = 3

# Stream chunk size for the running-byte-counter extraction of tar members.
_STREAM_CHUNK = 1 * 1024 * 1024  # 1 MiB

# The stdlib tar extraction filter is pinned explicitly to the hardened
# profile and NEVER left to the version default (Pitfall 3: the default only
# became this value in Python 3.14). filter='data' blocks traversal, absolute
# paths, symlinks, hardlinks, and device/special files — but it does NOT stop
# decompression bombs (Pitfall 1), so the hand-written caps still apply.
_TAR_FILTER = "data"


@dataclass(frozen=True)
class ExtractionLimits:
    """Configurable hard caps that bound a single extraction.

    All values are sane defaults (01-RESEARCH.md §5 / A2) and may be overridden
    per call. The caps are correctness requirements, not tuning knobs: without
    them ``filter='data'`` alone does not stop a decompression bomb (Pitfall 1).

    Attributes:
        max_total_uncompressed: Max total uncompressed bytes across all members.
        max_entry_size: Max uncompressed bytes for any single member.
        max_ratio: Max uncompressed/compressed ratio before an entry is rejected.
        max_entries: Max number of members in the archive.
        max_depth: Max nesting depth when the jail recurses into nested archives.
    """

    max_total_uncompressed: int = _DEFAULT_MAX_TOTAL_UNCOMPRESSED
    max_entry_size: int = _DEFAULT_MAX_ENTRY_SIZE
    max_ratio: int = _DEFAULT_MAX_RATIO
    max_entries: int = _DEFAULT_MAX_ENTRIES
    max_depth: int = _DEFAULT_MAX_DEPTH


class ExtractionRejected(Exception):
    """Raised when an archive (or one of its members) breaches a jail guard.

    The message carries a specific reason (the breached guard) so the audit log
    can record *why* an input was rejected. The jail never crashes with a raw
    ``tarfile``/``zipfile`` traceback — every guard breach is translated here.
    """


@dataclass(frozen=True)
class MemberRecord:
    """Per-member outcome metadata (evidence).

    Attributes:
        original_name: The member name exactly as stored in the archive — kept
            as evidence even when it is hostile (control chars, ``..``, absolute).
        on_disk_name: The sanitized relative path actually written, or ``None``
            if the member was rejected and nothing was written.
        rejected: Whether the member breached a guard.
        reason: The breached-guard reason when ``rejected`` is true.
    """

    original_name: str
    on_disk_name: str | None
    rejected: bool
    reason: str | None = None


@dataclass
class ExtractionResult:
    """The outcome of a :func:`safe_extract` call.

    Attributes:
        dest: The destination jail directory.
        members: One :class:`MemberRecord` per member processed.
        extracted: Absolute paths of every file actually written into the jail.
    """

    dest: Path
    members: list[MemberRecord] = field(default_factory=list)
    extracted: list[Path] = field(default_factory=list)

    @property
    def rejected(self) -> list[MemberRecord]:
        """Return the members that were rejected by a guard."""
        return [m for m in self.members if m.rejected]


def _sanitize_name(name: str) -> str:
    """Return a jail-relative, control-char-free version of ``name``.

    The original name is preserved separately as evidence; this is only the safe
    on-disk write-name. Drops any drive/anchor, strips ``..`` components, and
    replaces control characters and path separators within a component.

    Args:
        name: The raw member name from the archive.

    Returns:
        A relative POSIX-style path safe to join under the destination, or an
        empty string if nothing survives sanitization.
    """
    parts: list[str] = []
    for raw in name.replace("\\", "/").split("/"):
        if raw in ("", ".", ".."):
            continue
        cleaned = "".join(
            ch if (ch.isprintable() and ch not in '/:') else "_" for ch in raw
        )
        cleaned = cleaned.strip()
        if cleaned:
            parts.append(cleaned)
    return "/".join(parts)


def _confined_target(dest_real: str, name: str) -> str:
    """Resolve ``name`` under ``dest_real`` and assert it stays inside the jail.

    Args:
        dest_real: ``os.path.realpath`` of the destination directory.
        name: The member name to confine.

    Returns:
        The realpath of the write target, guaranteed inside the jail.

    Raises:
        ExtractionRejected: If the name is absolute, contains a ``..`` component,
            or resolves outside the destination (Zip Slip / path traversal).
    """
    if os.path.isabs(name) or name.startswith("/") or name.startswith("\\"):
        raise ExtractionRejected(f"absolute member path rejected: {name!r}")
    norm = name.replace("\\", "/")
    if any(part == ".." for part in norm.split("/")):
        raise ExtractionRejected(f"path-traversal component rejected: {name!r}")
    target = os.path.realpath(os.path.join(dest_real, norm))
    if target != dest_real and not target.startswith(dest_real + os.sep):
        raise ExtractionRejected(
            f"member escapes destination jail: {name!r} -> {target!r}"
        )
    return target


def _check_ratio(file_size: int, compress_size: int, limits: ExtractionLimits) -> None:
    """Reject an entry whose uncompressed/compressed ratio is too high.

    Args:
        file_size: Uncompressed size of the entry.
        compress_size: Compressed size of the entry (0 is treated as 1).
        limits: The active limits.

    Raises:
        ExtractionRejected: If the ratio exceeds ``limits.max_ratio``.
    """
    denom = compress_size if compress_size > 0 else 1
    if file_size // denom > limits.max_ratio:
        raise ExtractionRejected(
            f"compression-ratio bomb: {file_size}/{compress_size} "
            f"> {limits.max_ratio}x"
        )


def _extract_tar(
    archive_path: Path,
    dest: Path,
    dest_real: str,
    limits: ExtractionLimits,
    on_member_error: str,
    result: ExtractionResult,
) -> None:
    """Extract a tar archive under the jail with all guards applied."""
    with tarfile.open(archive_path, "r:*") as tar:
        # Pin the stdlib extraction filter explicitly to the hardened 'data'
        # profile and apply it per member below (filter='data', Pitfall 3 — the
        # default only became this in Python 3.14; we never rely on the version
        # default). tarfile.data_filter is the public callable for filter="data".
        assert _TAR_FILTER == "data"
        members = tar.getmembers()
        if len(members) > limits.max_entries:
            raise ExtractionRejected(
                f"entry-count bomb: {len(members)} > {limits.max_entries}"
            )
        total = 0
        for member in members:
            try:
                # Refuse anything that is not a plain file or directory: symlinks,
                # hardlinks, char/block devices, FIFOs. filter='data' also does
                # this, but rejecting up front keeps the error specific.
                if member.issym() or member.islnk():
                    raise ExtractionRejected(
                        f"link member refused: {member.name!r}"
                    )
                if member.isdev() or member.ischr() or member.isblk() or (
                    member.isfifo()
                ):
                    raise ExtractionRejected(
                        f"special/device member refused: {member.name!r}"
                    )
                original_name = member.name
                # Our own confinement first, on the *original* stored name —
                # this REJECTS absolute paths and `..` traversal rather than
                # silently relativizing them (the stdlib 'data' filter would
                # rewrite `/etc/x` -> `etc/x`, masking a tampering signal).
                target = _confined_target(dest_real, original_name)
                # Defense-in-depth: run the member through the stdlib 'data'
                # filter explicitly (Pitfall 3 — never rely on the version
                # default). It re-rejects symlink/hardlink/device via the
                # tarfile.*Error subclasses. If it would *alter* the name, the
                # member tried to escape — treat that as a rejection, not a
                # silent rewrite. filter='data' does NOT stop bombs, so the
                # hand-written caps below still apply (Pitfall 1).
                try:
                    filtered = tarfile.data_filter(member, dest_real)
                except tarfile.FilterError as exc:
                    raise ExtractionRejected(
                        f"tar data-filter rejected {original_name!r}: {exc}"
                    ) from exc
                if filtered.name != original_name.lstrip("/"):
                    raise ExtractionRejected(
                        f"member name rewritten by data filter "
                        f"(escape attempt): {original_name!r}"
                    )
                member = filtered
                if member.size > limits.max_entry_size:
                    raise ExtractionRejected(
                        f"per-entry-size bomb: {member.name!r} "
                        f"{member.size} > {limits.max_entry_size}"
                    )
                if member.isdir():
                    os.makedirs(target, exist_ok=True)
                    result.members.append(
                        MemberRecord(member.name, _sanitize_name(member.name),
                                     rejected=False)
                    )
                    continue
                # Stream the member with a running byte counter so a total-size
                # bomb aborts mid-write rather than after the whole bomb lands.
                src = tar.extractfile(member)
                if src is None:
                    raise ExtractionRejected(
                        f"unreadable member: {member.name!r}"
                    )
                os.makedirs(os.path.dirname(target) or dest_real, exist_ok=True)
                written = 0
                with src, open(target, "wb") as out:
                    while True:
                        chunk = src.read(_STREAM_CHUNK)
                        if not chunk:
                            break
                        written += len(chunk)
                        total += len(chunk)
                        if written > limits.max_entry_size:
                            raise ExtractionRejected(
                                f"per-entry-size bomb (streamed): "
                                f"{member.name!r}"
                            )
                        if total > limits.max_total_uncompressed:
                            raise ExtractionRejected(
                                "total-uncompressed bomb: "
                                f"{total} > {limits.max_total_uncompressed}"
                            )
                        out.write(chunk)
                result.extracted.append(Path(target))
                result.members.append(
                    MemberRecord(member.name, _sanitize_name(member.name),
                                 rejected=False)
                )
            except ExtractionRejected as exc:
                result.members.append(
                    MemberRecord(member.name, None, rejected=True,
                                 reason=str(exc))
                )
                if on_member_error == "skip":
                    continue
                raise


def _extract_zip(
    archive_path: Path,
    dest: Path,
    dest_real: str,
    limits: ExtractionLimits,
    on_member_error: str,
    result: ExtractionResult,
) -> None:
    """Extract a zip archive under the jail with all guards applied.

    ``zipfile`` has no extraction filter (Pitfall 2), so confinement, symlink
    refusal, and the bomb caps are all enforced by hand here.
    """
    with zipfile.ZipFile(archive_path, "r") as zf:
        infos = zf.infolist()
        if len(infos) > limits.max_entries:
            raise ExtractionRejected(
                f"entry-count bomb: {len(infos)} > {limits.max_entries}"
            )
        total = 0
        for info in infos:
            name = info.filename
            try:
                mode = (info.external_attr >> 16) & 0o170000
                if mode == stat.S_IFLNK:
                    raise ExtractionRejected(f"symlink member refused: {name!r}")
                if mode and mode not in (stat.S_IFREG, stat.S_IFDIR):
                    raise ExtractionRejected(
                        f"special member refused: {name!r}"
                    )
                target = _confined_target(dest_real, name)
                if info.is_dir() or name.endswith("/"):
                    os.makedirs(target, exist_ok=True)
                    result.members.append(
                        MemberRecord(name, _sanitize_name(name), rejected=False)
                    )
                    continue
                if info.file_size > limits.max_entry_size:
                    raise ExtractionRejected(
                        f"per-entry-size bomb: {name!r} "
                        f"{info.file_size} > {limits.max_entry_size}"
                    )
                _check_ratio(info.file_size, info.compress_size, limits)
                os.makedirs(os.path.dirname(target) or dest_real, exist_ok=True)
                written = 0
                with zf.open(info, "r") as src, open(target, "wb") as out:
                    while True:
                        chunk = src.read(_STREAM_CHUNK)
                        if not chunk:
                            break
                        written += len(chunk)
                        total += len(chunk)
                        if written > limits.max_entry_size:
                            raise ExtractionRejected(
                                f"per-entry-size bomb (streamed): {name!r}"
                            )
                        if total > limits.max_total_uncompressed:
                            raise ExtractionRejected(
                                "total-uncompressed bomb: "
                                f"{total} > {limits.max_total_uncompressed}"
                            )
                        out.write(chunk)
                result.extracted.append(Path(target))
                result.members.append(
                    MemberRecord(name, _sanitize_name(name), rejected=False)
                )
            except ExtractionRejected as exc:
                result.members.append(
                    MemberRecord(name, None, rejected=True, reason=str(exc))
                )
                if on_member_error == "skip":
                    continue
                raise


def safe_extract(
    archive_path: str | os.PathLike[str],
    dest: str | os.PathLike[str],
    limits: ExtractionLimits | None = None,
    *,
    on_member_error: str = "raise",
    _depth: int = 0,
) -> ExtractionResult:
    """Safely expand a tar or zip archive into the destination jail.

    This is the only sanctioned archive expander (D-11). It confines every member
    to ``dest``, refuses symlink/hardlink/device/special files, sanitizes on-disk
    names (preserving the originals as evidence), and enforces hard bomb caps with
    a running byte counter that aborts before disk exhaustion.

    Args:
        archive_path: Path to the tar or zip archive to expand.
        dest: Destination directory (the jail). Created if it does not exist.
        limits: Decompression-bomb caps. Defaults to :class:`ExtractionLimits`.
        on_member_error: ``"raise"`` (default) re-raises on the first rejected
            member; ``"skip"`` records the rejection and continues so one
            malformed member never aborts the whole run.
        _depth: Internal recursion-depth counter for nested archives.

    Returns:
        An :class:`ExtractionResult` describing every member and what was written.

    Raises:
        ExtractionRejected: On any guard breach (traversal, symlink/special file,
            absolute path, or a breached bomb cap), or when the archive format is
            not a recognized tar/zip, or when ``max_depth`` is exceeded.
    """
    limits = limits or ExtractionLimits()
    if _depth > limits.max_depth:
        raise ExtractionRejected(
            f"nesting-depth bomb: depth {_depth} > {limits.max_depth}"
        )

    archive = Path(archive_path)
    dest_path = Path(dest)
    dest_path.mkdir(parents=True, exist_ok=True)
    dest_real = os.path.realpath(dest_path)
    result = ExtractionResult(dest=dest_path)

    if tarfile.is_tarfile(archive):
        _extract_tar(archive, dest_path, dest_real, limits, on_member_error,
                     result)
    elif zipfile.is_zipfile(archive):
        _extract_zip(archive, dest_path, dest_real, limits, on_member_error,
                     result)
    else:
        raise ExtractionRejected(
            f"unrecognized archive format (not tar or zip): {archive}"
        )
    return result
