"""Locate + order rotated/gz log sets via the FS seam (D-45, Pitfall 4).

Linux log rotation produces sets like ``auth.log`` (live) / ``auth.log.1`` /
``auth.log.2.gz`` (oldest, compressed). Correct forensic ordering is
**oldest→newest** — NOT lexical — because (a) RFC3164 year inference walks the
records append-ordered and (b) a fixed file order fixes the
``insert_timeline_events`` order and thus the store's surrogate-id tiebreak (the
CR-01 deterministic-tied-order guarantee, Pitfall 3).

This module is pure logic over the FS seam's outputs: it accepts ``FileEntry``-like
rows (anything exposing ``path`` + a ``read_random(offset, size)`` closure) and
reads bytes through that closure, decompressing ``.gz`` members with stdlib
``gzip``. It **imports no pytsk3/pyewf** (D-14) and adds **no runtime dependency**
(D-43) — only stdlib ``re``/``io``/``gzip``.
"""

from __future__ import annotations

import gzip
import io
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

# ``LogMember`` / ``LogSet`` / ``CompletenessFinding`` are the value types the
# public functions here return, so they stay exported even though no caller
# imports them by name today — a caller cannot annotate a result it cannot name.
# The basename lists and the inflation cap are internal policy constants
# (documented in docs/CONFIGURATION.md) and are private.
__all__ = [
    "CompletenessFinding",
    "LogMember",
    "LogSet",
    "decode_member",
    "discover_log_sets",
    "discover_shell_histories",
    "order_rotated_set",
]

# Hard cap on the DECOMPRESSED size of a single rotated ``.gz`` log member
# (WR-05). A ``.gz`` member's on-disk (compressed) size does NOT bound its
# inflated size, so a small crafted member can expand to a memory-exhausting
# blob. The log path inflates one in-memory member directly, so the cap is
# enforced right here: the inflate is read in bounded chunks and refused once it
# crosses this limit. 256 MiB is far larger than any real rotated log, and small
# enough to stop a bomb.
_MAX_GZ_UNCOMPRESSED = 256 * 1024 * 1024

# The /var/log base names the rotated-set discovery collects. These are the
# RFC3164/RFC5424 system logs (auth + syslog) the auth/syslog parsers handle.
# Order is the declared scan order. Shell history is NOT here — it lives at
# per-user dotfile paths (see :data:`_SHELL_HISTORY_BASENAMES` /
# :func:`discover_shell_histories`), not under /var/log, and does not rotate.
_DEFAULT_LOG_BASENAMES: tuple[str, ...] = (
    "auth.log",
    "secure",
    "syslog",
    "messages",
)

# Per-user shell-history dotfile leaf names (LOG-03). These are discovered on a
# SEPARATE path from the rotated /var/log sets: they live at
# ``/home/<user>/.bash_history`` (and ``/root/.bash_history``), carry no rotation
# suffix, and must each be parsed as its own standalone "set" so the per-user
# actor (``/home/<user>``) and the no-chronology tamperability finding (D-44)
# stay attached. Matches :meth:`ShellHistoryParser.matches`.
_SHELL_HISTORY_BASENAMES: frozenset[str] = frozenset(
    {".bash_history", ".zsh_history", ".history"}
)

# A rotated member's trailing index: ``.1`` (numeric) or ``.2.gz`` (numeric+gz)
# or a ``dateext`` ``-YYYYMMDD`` / ``.YYYYMMDD`` suffix. The live file has no
# index. ``.gz`` is captured separately so a gz member orders BEFORE the non-gz
# of the same index (it is the older, already-rotated copy).
_NUMERIC_SUFFIX = re.compile(r"^(?P<base>.+?)\.(?P<idx>\d+)(?P<gz>\.gz)?$")
_DATEEXT_SUFFIX = re.compile(r"^(?P<base>.+?)[.\-](?P<date>\d{8})(?P<gz>\.gz)?$")


@dataclass(frozen=True, slots=True)
class LogMember:
    """One ordered member of a rotated log set.

    Attributes:
        path: The member's full filesystem path.
        index: Rotation index — ``0`` for the live file, higher = older.
        is_gz: ``True`` when the member is gzip-compressed.
        order_key: The sort key used to place this member oldest→newest.
        present: ``True`` when the member was actually found in the image.
    """

    path: str
    index: int
    is_gz: bool
    order_key: tuple[int, int]
    present: bool = True


@dataclass(frozen=True, slots=True)
class LogSet:
    """A rotated log set, members ordered oldest→newest, with a completeness finding."""

    basename: str
    members: tuple[LogMember, ...]
    finding: CompletenessFinding


@dataclass(frozen=True, slots=True)
class CompletenessFinding:
    """A log-completeness finding (D-45 honesty): which indices are present/absent."""

    basename: str
    present_indices: tuple[int, ...]
    missing_indices: tuple[int, ...]
    member_count: int
    note: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)


def _parse_member(path: str, basename: str) -> tuple[int, bool] | None:
    """Return ``(index, is_gz)`` for a member of ``basename``, or ``None``.

    The live file (``/dir/<basename>``) is index 0. ``<basename>.N[.gz]`` is the
    numeric rotation; ``<basename>.YYYYMMDD[.gz]`` is the dateext rotation (mapped
    to a synthetic descending index so newer dates order newer).
    """
    name = path.rsplit("/", 1)[-1]
    if name == basename:
        return 0, False
    if name == basename + ".gz":
        return 0, True
    m = _NUMERIC_SUFFIX.match(name)
    if m and m.group("base") == basename:
        return int(m.group("idx")), bool(m.group("gz"))
    d = _DATEEXT_SUFFIX.match(name)
    if d and d.group("base") == basename:
        # Higher date = newer; map to a negative index so it sorts as a small
        # rotation index (newer) while staying distinct from the numeric scheme.
        return -int(d.group("date")), bool(d.group("gz"))
    return None


def order_rotated_set(paths: Sequence[Any]) -> list[LogMember]:
    """Order a rotated set's paths oldest→newest (D-45, Pitfall 4).

    Accepts raw path strings or ``FileEntry``-like rows (anything with a ``path``
    attribute). The basename is inferred from the live (index-0) member or, when
    absent, the longest common stem. Ordering is by ``(index, gz)`` descending so
    the highest numeric index comes first (oldest), a ``.gz`` member precedes the
    non-gz of the same index, and the live file (index 0, non-gz) is last.

    Args:
        paths: The set's members (shuffled order accepted).

    Returns:
        :class:`LogMember` list ordered oldest→newest.
    """
    raw = [(p if isinstance(p, str) else p.path) for p in paths]
    basename = _infer_basename(raw)

    members: list[LogMember] = []
    for path in raw:
        parsed = _parse_member(path, basename)
        if parsed is None:
            # Not recognisably part of the set; keep it but place it newest.
            index, is_gz = 0, path.endswith(".gz")
        else:
            index, is_gz = parsed
        # oldest→newest: larger index first; within an index, gz (older) first.
        order_key = (-index, 0 if is_gz else 1)
        members.append(
            LogMember(path=path, index=index, is_gz=is_gz, order_key=order_key)
        )
    members.sort(key=lambda mbr: mbr.order_key)
    return members


def _infer_basename(paths: Iterable[str]) -> str:
    """Infer the rotated set's base name from its members."""
    names = [p.rsplit("/", 1)[-1] for p in paths]
    for name in names:
        # The live file is the member with no numeric/date/gz suffix.
        if not _NUMERIC_SUFFIX.match(name) and not name.endswith(".gz"):
            return name
    # Fall back to stripping the first known rotation suffix off any member.
    for name in names:
        m = _NUMERIC_SUFFIX.match(name)
        if m:
            return m.group("base")
        if name.endswith(".gz"):
            return name[: -len(".gz")]
    return names[0] if names else ""


def _completeness(basename: str, members: Sequence[LogMember]) -> CompletenessFinding:
    """Build the D-45 completeness finding from the ordered members."""
    numeric = sorted({m.index for m in members if m.index >= 0})
    present = tuple(numeric)
    missing: tuple[int, ...] = ()
    note = "log set reassembled oldest→newest"
    if numeric:
        full = set(range(0, max(numeric) + 1))
        missing = tuple(sorted(full - set(numeric)))
        if missing:
            note = (
                f"log set may be incomplete: rotation indices {list(missing)} "
                "absent (rotated out / never present)"
            )
    return CompletenessFinding(
        basename=basename,
        present_indices=present,
        missing_indices=missing,
        member_count=len(members),
        note=note,
    )


def discover_log_sets(
    rows: Iterable[Any], *, basenames: Sequence[str] = _DEFAULT_LOG_BASENAMES
) -> list[LogSet]:
    """Group FS-seam rows into rotated log sets, ordered oldest→newest (D-45).

    Args:
        rows: ``FileEntry``-like rows from the FS seam (must expose ``path``).
        basenames: The log base names to collect (default Wave-1: auth.log/secure).

    Returns:
        One :class:`LogSet` per discovered base name with a completeness finding.
    """
    by_base: dict[str, list[Any]] = {b: [] for b in basenames}
    for row in rows:
        path = row.path if not isinstance(row, str) else row
        name = path.rsplit("/", 1)[-1]
        for base in basenames:
            if name == base or name.startswith(base + "."):
                by_base[base].append(row)
                break

    sets: list[LogSet] = []
    for base in basenames:
        group = by_base[base]
        if not group:
            continue
        ordered = order_rotated_set(group)
        # Re-attach the original rows by path so callers keep the read closure.
        by_path = {(r.path if not isinstance(r, str) else r): r for r in group}
        members_with_rows = [(m, by_path.get(m.path)) for m in ordered]
        sets.append(
            LogSet(
                basename=base,
                members=tuple(m for m, _ in members_with_rows),
                finding=_completeness(base, ordered),
            )
        )
    return sets


def discover_shell_histories(
    rows: Iterable[Any], *, basenames: frozenset[str] = _SHELL_HISTORY_BASENAMES
) -> list[LogSet]:
    """Find per-user shell-history files as standalone single-member sets (LOG-03).

    Shell history is NOT a rotated /var/log set: each ``/home/<user>/.bash_history``
    (or ``.zsh_history``/``.history``, plus ``/root/...``) is its own file with no
    rotation siblings. Each match becomes a one-member :class:`LogSet` whose
    ``basename`` is the FULL path (so the orchestrator forwards the path to the
    parser's ``ctx`` for the per-user actor) and whose member carries the row's
    read closure. Returned in encounter order so the insert order — and therefore
    the store surrogate-id tiebreak — stays deterministic (Pitfall 3).

    Args:
        rows: ``FileEntry``-like rows from the FS seam (must expose ``path``).
        basenames: The shell-history dotfile leaf names to collect.

    Returns:
        One single-member :class:`LogSet` per discovered shell-history file.
    """
    sets: list[LogSet] = []
    for row in rows:
        path = row.path if not isinstance(row, str) else row
        leaf = path.rsplit("/", 1)[-1]
        if leaf not in basenames:
            continue
        member = LogMember(path=path, index=0, is_gz=False, order_key=(0, 1))
        finding = CompletenessFinding(
            basename=path,
            present_indices=(0,),
            missing_indices=(),
            member_count=1,
            note="shell history is a single, non-rotated per-user file",
        )
        sets.append(LogSet(basename=path, members=(member,), finding=finding))
    return sets


def decode_member(raw: bytes, *, is_gz: bool) -> str:
    """Decode a member's bytes to text, decompressing gz, as DATA (Security V5).

    ``.gz`` members are inflated with stdlib :class:`gzip.GzipFile` over an
    in-memory buffer; all bytes are decoded ``utf-8``/``errors="replace"`` (data
    only, never a write path). A truncated/garbage gz stream degrades to an empty
    decode rather than aborting the run (a corrupt rotated member must not lose
    the rest of the set).

    Args:
        raw: The member's raw bytes (as read through the seam closure).
        is_gz: Whether the member is gzip-compressed.

    Returns:
        The decoded log text (possibly empty for a corrupt gz member).
    """
    if not raw:
        return ""
    if is_gz:
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as gz:
                # Bounded inflate (WR-05): read in chunks and stop once the
                # decompressed size crosses _MAX_GZ_UNCOMPRESSED, so a small
                # crafted gz member cannot expand into a memory-exhausting blob.
                # ``gz.read(n)`` is the decompression-bomb-safe counterpart of an
                # unbounded ``gz.read()``. We read one chunk past the cap to
                # DETECT the breach, then refuse the member (return "") rather
                # than buffer the whole bomb or silently truncate evidence.
                chunks: list[bytes] = []
                total = 0
                chunk_size = 4 * 1024 * 1024  # 4 MiB
                while True:
                    chunk = gz.read(chunk_size)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > _MAX_GZ_UNCOMPRESSED:
                        # Decompression-bomb cap breached: refuse this member
                        # mid-stream, before the inflated bytes are retained. The
                        # rest of the rotated set is unaffected (a single bad
                        # member must not lose the others).
                        return ""
                    chunks.append(chunk)
                raw = b"".join(chunks)
        except (OSError, EOFError):
            return ""
    return raw.decode("utf-8", "replace")
