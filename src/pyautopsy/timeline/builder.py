"""Filesystem timeline producer — the MACB explosion (TIME-01 / D-23 / D-24).

This module is the first producer into the shared ``timeline_events`` model: it
reads the already-normalized Phase 2 ``files`` rows through the case store and
explodes each populated MACB timestamp into one normalized
:class:`~pyautopsy.case.TimelineEvent` (a file with four distinct populated
times yields up to four events). A ``None`` ``*_utc`` column produces NO event
(D-24 — the walk already mapped a 0 epoch to ``None``, so "0 epoch ⇒ not
recorded" propagates here with no extra logic).

Like :mod:`pyautopsy.core.walk` this module is part of the upper tiers and
**imports no native bindings** (no ``pytsk3``/``pyewf``): it reads case-store
rows only. It also **re-derives no timestamps** — the ``ts_utc`` sort key is the
walk's ``*_utc`` string copied **verbatim** (the timezone/FAT/zero-epoch work is
already done and tested in the walk, META-02). It writes through the store
inside one transaction (no raw SQL) and is analytical-only (no wall-clock).
"""

from __future__ import annotations

from pyautopsy.case import FileRow, TimelineEvent
from pyautopsy.case.store import CaseStore

# MACB column -> event_type map (D-24). Order is the natural M/A/C/B order; the
# persisted total order is imposed once by the store's D-26 read, not here.
_MACB: tuple[tuple[str, str], ...] = (
    ("mtime_utc", "modified"),
    ("atime_utc", "accessed"),
    ("ctime_utc", "changed"),
    ("crtime_utc", "born"),
)


def _explode(file_row: FileRow) -> list[TimelineEvent]:
    """Explode one :class:`FileRow` into its populated-MACB timeline events.

    Pure transform (no I/O): for each populated ``*_utc`` column emit one event
    of the mapped type, copying the timestamp string **verbatim** (D-24, the
    walk already normalized it). A ``None`` column yields no event.

    Args:
        file_row: The Phase 2 file row to explode.

    Returns:
        Zero to four :class:`TimelineEvent` rows — one per populated MACB time.
    """
    # Build actor from ONLY the populated uid/gid components (WR-05): emitting a
    # literal "uid=None"/"gid=None" into an evidence-presentation artifact is
    # misleading (a reviewer cannot tell "unknown" from a literal value). A
    # half-populated row yields e.g. "uid=0" alone; both-absent yields None.
    parts: list[str] = []
    if file_row.uid is not None:
        parts.append(f"uid={file_row.uid}")
    if file_row.gid is not None:
        parts.append(f"gid={file_row.gid}")
    actor: str | None = ",".join(parts) if parts else None

    source = (
        f"filesystem:{file_row.fs_type}" if file_row.fs_type else "filesystem"
    )

    events: list[TimelineEvent] = []
    for col, etype in _MACB:
        ts = getattr(file_row, col)
        if ts is None:  # D-24: zero/None ⇒ no event
            continue
        events.append(
            TimelineEvent(
                evidence_source_id=file_row.evidence_source_id,
                ts_utc=ts,  # verbatim — never re-derived from an epoch
                source=source,
                event_type=etype,
                volume_id=file_row.volume_id,
                volume_offset=file_row.volume_offset,
                path=file_row.path,
                meta_addr=file_row.meta_addr,
                actor=actor,
                file_id=file_row.id,
            )
        )
    return events


# Public alias: the explosion transform is exercised directly by tests/consumers.
explode = _explode


def build_timeline(store: CaseStore, evidence_source_id: int) -> int:
    """Build the filesystem timeline for one evidence source (TIME-01).

    Reads every ``files`` row for the source, explodes each into its populated
    MACB events (D-24), and bulk-inserts them through the store inside a single
    transaction (WR-01). The result is analytical-only — the inserted event
    count — with no wall-clock metadata (cf. :class:`WalkResult`).

    Args:
        store: The open case store to read files from and write events into.
        evidence_source_id: The owning evidence-source id to build a timeline
            for.

    Returns:
        The number of timeline events inserted.
    """
    events: list[TimelineEvent] = []
    for file_row in store.get_files(evidence_source_id):
        events.extend(_explode(file_row))

    with store.transaction():
        store.insert_timeline_events(events)

    return len(events)
