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
from typing import Any, Protocol

__all__ = [
    "LogMember",
    "LogSet",
    "CompletenessFinding",
    "order_rotated_set",
    "discover_log_sets",
    "decode_member",
    "DEFAULT_LOG_BASENAMES",
]

# The log base names this slice (Wave 1) discovers. Wave-2 parsers extend this
# without touching the orchestrator (EXT-01). Order is the declared scan order.
DEFAULT_LOG_BASENAMES: tuple[str, ...] = ("auth.log", "secure")

# A rotated member's trailing index: ``.1`` (numeric) or ``.2.gz`` (numeric+gz)
# or a ``dateext`` ``-YYYYMMDD`` / ``.YYYYMMDD`` suffix. The live file has no
# index. ``.gz`` is captured separately so a gz member orders BEFORE the non-gz
# of the same index (it is the older, already-rotated copy).
_NUMERIC_SUFFIX = re.compile(r"^(?P<base>.+?)\.(?P<idx>\d+)(?P<gz>\.gz)?$")
_DATEEXT_SUFFIX = re.compile(r"^(?P<base>.+?)[.\-](?P<date>\d{8})(?P<gz>\.gz)?$")


class _SeamRow(Protocol):
    """The minimal FS-seam row shape discover consumes (a ``FileEntry`` subset)."""

    path: str

    @property
    def read_random(self) -> Any:  # (offset, size) -> bytes | None
        ...


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
    rows: Iterable[Any], *, basenames: Sequence[str] = DEFAULT_LOG_BASENAMES
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
                raw = gz.read()
        except (OSError, EOFError):
            return ""
    return raw.decode("utf-8", "replace")
