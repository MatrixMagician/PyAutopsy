"""WR-02 / WR-06 regression: CaseStore boundary reads for orchestrators.

The five orchestrators (walk/recover/search/logs/knownfiles) used to each issue
their own inline ``SELECT id FROM evidence_sources ORDER BY id DESC LIMIT 1``,
violating the documented "no raw SQL outside the store" boundary (WR-02). They now
route through ``CaseStore.get_latest_evidence_source_id``. ``run_logs`` likewise
gates its filesystem-MACB backfill through
``CaseStore.has_timeline_events_with_source_prefix`` (WR-06) instead of
"any timeline event exists". These tests pin both store contracts.
"""

from __future__ import annotations

from pathlib import Path

from pyautopsy.case import (
    Case,
    CaseStore,
    EvidenceSource,
    TimelineEvent,
)


def _seed_source(store: CaseStore, image_path: str = "/a.dd") -> int:
    case_id = store.insert_case(Case(name="c", examiner="ex"))
    return store.insert_evidence_source(
        EvidenceSource(
            case_id=case_id,
            evidence_id="EV-1",
            path=image_path,
            image_type="raw",
        )
    )


def test_get_latest_evidence_source_id_none_when_empty(case_dir: Path) -> None:
    """Returns None (not an error) when no evidence source exists (WR-02)."""
    with CaseStore.create(case_dir) as store:
        store.insert_case(Case(name="c", examiner="ex"))
        assert store.get_latest_evidence_source_id() is None


def test_get_latest_evidence_source_id_returns_newest(case_dir: Path) -> None:
    """Returns the most-recently-inserted evidence-source id (WR-02)."""
    with CaseStore.create(case_dir) as store:
        case_id = store.insert_case(Case(name="c", examiner="ex"))
        store.insert_evidence_source(
            EvidenceSource(
                case_id=case_id, evidence_id="A", path="/a.dd", image_type="raw"
            )
        )
        b = store.insert_evidence_source(
            EvidenceSource(
                case_id=case_id, evidence_id="B", path="/b.dd", image_type="raw"
            )
        )
        assert store.get_latest_evidence_source_id() == b


def _ts_event(source_id: int, source: str) -> TimelineEvent:
    return TimelineEvent(
        evidence_source_id=source_id,
        ts_utc="2024-01-01T00:00:00+00:00",
        source=source,
        event_type="modified",
        volume_id=0,
        volume_offset=0,
        path="/x",
    )


def test_has_timeline_events_with_source_prefix_gates_on_filesystem(
    case_dir: Path,
) -> None:
    """WR-06: the fs-backfill gate keys on filesystem events, not on ANY event.

    A prior log-only run leaves LOG events but no filesystem events; the gate must
    still report "no filesystem events" so the backfill runs, then report True once
    filesystem events exist (idempotent — no double backfill).
    """
    with CaseStore.create(case_dir) as store:
        sid = _seed_source(store)
        # Only LOG events exist (the standalone `logs` scenario).
        store.insert_timeline_events([_ts_event(sid, "auth")])
        assert store.has_timeline_events_with_source_prefix(sid, "filesystem") is False
        # After a filesystem backfill, the gate flips True (no double-backfill).
        store.insert_timeline_events([_ts_event(sid, "filesystem")])
        assert store.has_timeline_events_with_source_prefix(sid, "filesystem") is True
