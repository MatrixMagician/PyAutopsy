"""RED Wave-0 scaffold for the filesystem timeline producer (TIME-01).

These cover the exact pytest node IDs from 03-RESEARCH.md "Phase Requirements ->
Test Map" (lines 496-498). They reference ``pyautopsy.timeline.builder`` (the
producer Waves 1+ build) and the ``CaseStore`` D-26 ordered read, so every test
here is collected and RED until those land — never skipped.

Key contract (D-24): the MACB explosion emits one ``TimelineEvent`` per
*populated* ``*_utc`` column (``mtime_utc`` -> ``modified``, ``atime_utc`` ->
``accessed``, ``ctime_utc`` -> ``changed``, ``crtime_utc`` -> ``born``); a
``None`` column produces NO event. ``test_total_order`` is VALUE-LEVEL (W-3): it
asserts the exact ordered sequence on a fixture that ties on
ts+volume+offset+path, so dropping any D-26 tiebreak (event_type or meta_addr)
flips an adjacent pair and fails.
"""

from __future__ import annotations

from pathlib import Path

from pyautopsy.case import CaseStore, FileRow, TimelineEvent
from pyautopsy.case.store import _TIMELINE_MAPPER  # ordering helper proximity
from pyautopsy.core.ingest import run_ingest
from pyautopsy.core.walk import run_walk
from pyautopsy.timeline.builder import build_timeline
from tests.fixtures import make_fixtures


def _file_row(
    source_id: int,
    *,
    meta_addr: int,
    path: str = "/x",
    mtime: str | None = None,
    atime: str | None = None,
    ctime: str | None = None,
    crtime: str | None = None,
) -> FileRow:
    """Build a minimal FileRow with selected MACB times for explosion tests."""
    return FileRow(
        evidence_source_id=source_id,
        volume_id=0,
        volume_offset=0,
        path=path,
        name=path.rsplit("/", 1)[-1] or path,
        meta_addr=meta_addr,
        fs_type="ext4",
        allocated=True,
        uid=1000,
        gid=1000,
        mtime_utc=mtime,
        atime_utc=atime,
        ctime_utc=ctime,
        crtime_utc=crtime,
    )


def test_macb_explosion() -> None:
    """Each populated *_utc maps to one event of the right type; None -> none.

    A file with three populated times yields exactly three events; the absent
    ``atime_utc`` yields no ``accessed`` event (D-24).
    """
    from pyautopsy.timeline.builder import explode

    row = _file_row(
        1,
        meta_addr=11,
        mtime="2026-01-01T00:00:00+00:00",
        atime=None,
        ctime="2026-01-02T00:00:00+00:00",
        crtime="2026-01-03T00:00:00+00:00",
    )
    events = explode(row)

    by_type = {e.event_type: e.ts_utc for e in events}
    assert by_type == {
        "modified": "2026-01-01T00:00:00+00:00",
        "changed": "2026-01-02T00:00:00+00:00",
        "born": "2026-01-03T00:00:00+00:00",
    }
    assert "accessed" not in by_type
    assert all(isinstance(e, TimelineEvent) for e in events)


def test_total_order() -> None:
    """The production read imposes the exact D-26 total order (W-3, value-level).

    The fixture deliberately includes events that TIE on
    ts_utc + volume_id + volume_offset + path and differ ONLY on event_type and
    meta_addr, plus a later-timestamp event. The assertion is the FULL ordered
    identifier sequence: dropping the event_type tiebreak flips the
    (changed/modified) pair, and dropping the meta_addr tiebreak flips the two
    'changed' events — each gates a distinct adjacent pair.
    """
    ts = "2026-01-01T00:00:00+00:00"
    later = "2026-02-02T00:00:00+00:00"
    events = [
        TimelineEvent(1, later, "filesystem", "born", 0, 0, "/a", meta_addr=1),
        TimelineEvent(1, ts, "filesystem", "modified", 0, 0, "/a", meta_addr=5),
        TimelineEvent(1, ts, "filesystem", "changed", 0, 0, "/a", meta_addr=5),
        TimelineEvent(1, ts, "filesystem", "changed", 0, 0, "/a", meta_addr=2),
    ]

    # Feed through the production ordering path: persist then read back ordered.
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        with CaseStore.create(Path(td) / "case") as store:
            with store.transaction():
                from pyautopsy.case import Case, EvidenceSource

                case_id = store.insert_case(Case(name="c", examiner="x"))
                source_id = store.insert_evidence_source(
                    EvidenceSource(
                        case_id=case_id,
                        evidence_id="E1",
                        path="/x.dd",
                        image_type="raw",
                    )
                )
                store.insert_timeline_events(
                    [
                        TimelineEvent(
                            source_id,
                            e.ts_utc,
                            e.source,
                            e.event_type,
                            e.volume_id,
                            e.volume_offset,
                            e.path,
                            meta_addr=e.meta_addr,
                        )
                        for e in events
                    ]
                )
            ordered = store.get_timeline_events(source_id)

    observed = [(e.ts_utc, e.path, e.event_type, e.meta_addr) for e in ordered]
    assert observed == [
        (ts, "/a", "changed", 2),
        (ts, "/a", "changed", 5),
        (ts, "/a", "modified", 5),
        (later, "/a", "born", 1),
    ]


def test_total_order_null_meta_addr_is_deterministic() -> None:
    """Distinct deleted/orphan events tying on six D-26 keys still order stably (CR-01).

    Builds ≥2 DISTINCT events that tie on ts_utc + volume + path + event_type
    with NULL ``meta_addr`` (the reclaimed-path/orphan case the six-column order
    cannot separate). Two of them differ only on ``source``/``actor`` (the
    content tiebreaks); the final pair is byte-identical on every content column
    and is separated only by the surrogate ``id`` (insertion order). Asserts the
    fully-determined output sequence AND that repeated reads of the same DB are
    identical — i.e. the order never falls through to sqlite's rowid tiebreak.
    """
    ts = "2026-01-01T00:00:00+00:00"
    # All tie on (ts, vol 0/0, "/recovered", "modified") with meta_addr=None.
    # source/actor are the next content tiebreaks; the last two are identical on
    # every content column and rely on the surrogate-id (insertion) tiebreak.
    events = [
        TimelineEvent(
            1,
            ts,
            "filesystem:ext",
            "modified",
            0,
            0,
            "/recovered",
            meta_addr=None,
            actor="uid=1000",
        ),
        TimelineEvent(
            1,
            ts,
            "filesystem",
            "modified",
            0,
            0,
            "/recovered",
            meta_addr=None,
            actor="uid=1000",
        ),
        TimelineEvent(
            1,
            ts,
            "filesystem",
            "modified",
            0,
            0,
            "/recovered",
            meta_addr=None,
            actor="uid=0",
        ),
        TimelineEvent(
            1,
            ts,
            "filesystem",
            "modified",
            0,
            0,
            "/recovered",
            meta_addr=None,
            actor="uid=0",
        ),
    ]

    import tempfile

    from pyautopsy.case import Case, EvidenceSource

    with tempfile.TemporaryDirectory() as td:
        with CaseStore.create(Path(td) / "case") as store:
            with store.transaction():
                case_id = store.insert_case(Case(name="c", examiner="x"))
                source_id = store.insert_evidence_source(
                    EvidenceSource(
                        case_id=case_id,
                        evidence_id="E1",
                        path="/x.dd",
                        image_type="raw",
                    )
                )
                store.insert_timeline_events(
                    [
                        TimelineEvent(
                            source_id,
                            e.ts_utc,
                            e.source,
                            e.event_type,
                            e.volume_id,
                            e.volume_offset,
                            e.path,
                            meta_addr=e.meta_addr,
                            actor=e.actor,
                        )
                        for e in events
                    ]
                )
            first = store.get_timeline_events(source_id)
            second = store.get_timeline_events(source_id)

    # NULL meta_addr never crashes the ordering and yields a fully-determined
    # sequence: ts/path/event_type all tie, so source then actor then id decide.
    observed = [(e.source, e.actor, e.id) for e in first]
    assert observed == [
        ("filesystem", "uid=0", observed[0][2]),
        ("filesystem", "uid=0", observed[1][2]),
        ("filesystem", "uid=1000", observed[2][2]),
        ("filesystem:ext", "uid=1000", observed[3][2]),
    ]
    # The two byte-identical-content events are separated only by surrogate id,
    # in ascending (insertion) order — deterministic, never rowid-random.
    assert observed[0][2] < observed[1][2]
    # Repeated reads of the same DB are identical (no rowid tiebreak leak).
    assert [e.id for e in first] == [e.id for e in second]


def test_ext4_timeline(tiny_ext4_image: Path, case_dir: Path) -> None:
    """End-to-end on the committed ext4 fixture: known file MACB times appear.

    Ingest + walk + build_timeline; the known regular file's populated MACB
    times surface as events and the deleted entry is handled (no crash; its
    events, if any times survive, are present and ordered).
    """
    ingested = run_ingest(tiny_ext4_image, case_dir, examiner="X", evidence_id="E1")
    run_walk(tiny_ext4_image, case_dir, timezone="UTC")

    with CaseStore.open(case_dir) as store:
        n_events = build_timeline(store, ingested.evidence_source_id)
        events = store.get_timeline_events(ingested.evidence_source_id)

    assert n_events == len(events)
    assert events, "expected at least the known file's MACB events"
    # The known regular file is represented somewhere in the timeline.
    paths = {e.path for e in events}
    assert any(make_fixtures.FS_FILE_NAME in p for p in paths)
    # Events carry the D-24 event types only.
    assert {e.event_type for e in events} <= {
        "modified",
        "accessed",
        "changed",
        "born",
    }
    # ts_utc is copied verbatim as a UTC ISO-8601 string (D-10).
    assert all(e.ts_utc.endswith("+00:00") for e in events)
    # The insert mapping round-trips an event (keeps the mapper exercised).
    assert _TIMELINE_MAPPER.to_params(events[0])
