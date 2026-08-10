"""Tests for the SQLite case store (REPORT-01, D-01/D-02/D-03).

These prove the forensic spine: the case directory layout, the typed-core-columns
+ JSON-``attributes`` schema, chain-of-custody round-tripping, UTC-everywhere
timestamps, and the WAL / foreign-keys pragmas that keep the store crash-safe and
referentially sound.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from pyautopsy.case import (
    Case,
    CaseStore,
    EvidenceSource,
    FileRow,
    LogFinding,
    SearchHit,
    TimelineEvent,
    VolumeLimitation,
)


def _seed_evidence_source(store: CaseStore) -> int:
    """Insert a case + evidence source and return the evidence source id."""
    case_id = store.insert_case(Case(name="c", examiner="ex"))
    return store.insert_evidence_source(
        EvidenceSource(
            case_id=case_id,
            evidence_id="EV-1",
            path="/x.dd",
            image_type="raw",
        )
    )


def test_create_builds_directory_layout(case_dir: Path) -> None:
    """``CaseStore.create`` materialises the D-01 case directory layout."""
    with CaseStore.create(case_dir):
        pass
    assert case_dir.is_dir()
    assert (case_dir / "logs").is_dir()
    assert (case_dir / "exports").is_dir()
    assert (case_dir / "case.db").is_file()


def test_pragmas_wal_and_foreign_keys(case_dir: Path) -> None:
    """The case DB is opened WAL with foreign-key enforcement on."""
    with CaseStore.create(case_dir) as store:
        journal_mode = store.connection.execute(
            "PRAGMA journal_mode"
        ).fetchone()[0]
        foreign_keys = store.connection.execute(
            "PRAGMA foreign_keys"
        ).fetchone()[0]
    assert journal_mode.lower() == "wal"
    assert foreign_keys == 1


def test_case_round_trips(case_dir: Path) -> None:
    """A Case persisted then read back yields equal field values."""
    with CaseStore.create(case_dir) as store:
        case = Case(
            name="Operation Teapot",
            examiner="A. Examiner",
            notes="initial intake",
            attributes={"jurisdiction": "EU"},
        )
        case_id = store.insert_case(case)
        loaded = store.get_case(case_id)

    assert loaded.name == "Operation Teapot"
    assert loaded.examiner == "A. Examiner"
    assert loaded.notes == "initial intake"
    assert loaded.attributes == {"jurisdiction": "EU"}
    assert loaded.pyautopsy_version  # tool version recorded
    assert loaded.created_utc.endswith("+00:00")


def test_evidence_source_round_trips(case_dir: Path) -> None:
    """An EvidenceSource (COC metadata) round-trips equal."""
    with CaseStore.create(case_dir) as store:
        case_id = store.insert_case(Case(name="c", examiner="ex"))
        source = EvidenceSource(
            case_id=case_id,
            evidence_id="EV-001",
            path="/evidence/disk.E01",
            image_type="ewf",
            sha256="a" * 64,
            md5="b" * 32,
            byte_size=65536,
            acquired_utc="2026-05-30T10:00:00+00:00",
            tsk_version="4.12.0",
        )
        source_id = store.insert_evidence_source(source)
        loaded = store.get_evidence_source(source_id)

    assert loaded.case_id == case_id
    assert loaded.evidence_id == "EV-001"
    assert loaded.path == "/evidence/disk.E01"
    assert loaded.image_type == "ewf"
    assert loaded.sha256 == "a" * 64
    assert loaded.md5 == "b" * 32
    assert loaded.byte_size == 65536
    assert loaded.acquired_utc == "2026-05-30T10:00:00+00:00"
    assert loaded.tsk_version == "4.12.0"


def test_all_timestamp_columns_are_utc(case_dir: Path) -> None:
    """Every persisted timestamp ends in the explicit ``+00:00`` UTC offset."""
    with CaseStore.create(case_dir) as store:
        case_id = store.insert_case(Case(name="c", examiner="ex"))
        store.insert_evidence_source(
            EvidenceSource(
                case_id=case_id,
                evidence_id="EV-1",
                path="/x.dd",
                image_type="raw",
            )
        )
        rows = store.connection.execute(
            "SELECT created_utc FROM cases"
        ).fetchall()
        rows += store.connection.execute(
            "SELECT acquired_utc FROM evidence_sources "
            "WHERE acquired_utc IS NOT NULL"
        ).fetchall()
    for (ts,) in rows:
        assert ts.endswith("+00:00"), ts


def test_attributes_accepts_heterogeneous_keys(case_dir: Path) -> None:
    """An arbitrary attributes key round-trips without a schema change (D-02)."""
    weird = {"phase4_finding": [1, 2, 3], "nested": {"k": "v"}, "n": 42}
    with CaseStore.create(case_dir) as store:
        case_id = store.insert_case(
            Case(name="c", examiner="ex", attributes=weird)
        )
        loaded = store.get_case(case_id)
    assert loaded.attributes == weird


def test_file_row_round_trips(case_dir: Path) -> None:
    """A FileRow persisted inside a transaction reads back equal (META-01)."""
    with CaseStore.create(case_dir) as store:
        with store.transaction():
            source_id = _seed_evidence_source(store)
            file_id = store.insert_file(
                FileRow(
                    evidence_source_id=source_id,
                    volume_id=2,
                    volume_offset=1048576,
                    path="/dir/file1.txt",
                    name="file1.txt",
                    parent_addr=11,
                    meta_addr=12,
                    fs_type="ext4",
                    size=27,
                    allocated=True,
                    meta_type="reg",
                    attributes={"note": "round-trip"},
                )
            )
        loaded = store.get_file(file_id)

    assert loaded.evidence_source_id == source_id
    assert loaded.volume_id == 2
    assert loaded.volume_offset == 1048576
    assert loaded.path == "/dir/file1.txt"
    assert loaded.name == "file1.txt"
    assert loaded.parent_addr == 11
    assert loaded.meta_addr == 12
    assert loaded.fs_type == "ext4"
    assert loaded.size == 27
    assert loaded.allocated is True
    assert loaded.meta_type == "reg"
    assert loaded.attributes == {"note": "round-trip"}
    # Interface-first columns stay null until Plans 02-02/02-03 populate them.
    assert loaded.mtime_utc is None
    assert loaded.sha256 is None
    assert loaded.file_type is None


def test_file_row_deleted_status_round_trips(case_dir: Path) -> None:
    """A deleted (unallocated) entry round-trips with ``allocated is False``."""
    with CaseStore.create(case_dir) as store:
        with store.transaction():
            source_id = _seed_evidence_source(store)
            file_id = store.insert_file(
                FileRow(
                    evidence_source_id=source_id,
                    volume_id=0,
                    volume_offset=0,
                    path="/deleted.txt",
                    name="deleted.txt",
                    meta_addr=13,
                    allocated=False,
                )
            )
        loaded = store.get_file(file_id)
    assert loaded.allocated is False
    assert loaded.meta_addr == 13


def test_insert_files_bulk_executemany(case_dir: Path) -> None:
    """``insert_files`` bulk-inserts many rows inside an outer transaction."""
    with CaseStore.create(case_dir) as store:
        with store.transaction():
            source_id = _seed_evidence_source(store)
            rows = [
                FileRow(
                    evidence_source_id=source_id,
                    volume_id=0,
                    volume_offset=0,
                    path=f"/f{i}",
                    name=f"f{i}",
                    meta_addr=100 + i,
                    allocated=True,
                )
                for i in range(5)
            ]
            inserted = store.insert_files(rows)
        loaded = store.get_files(source_id)
    assert inserted == 5
    assert len(loaded) == 5
    assert [r.name for r in loaded] == [f"f{i}" for i in range(5)]


def test_files_volume_columns_are_not_null(case_dir: Path) -> None:
    """WR-06: ``files.volume_id``/``volume_offset`` reject NULL.

    ``FileRow`` types both as non-optional ``int`` and the walk always provides
    them (D-15). The schema now declares both NOT NULL so a NULL can never
    silently round-trip into a ``None`` in an ``int`` field; an attempt to insert
    one is a loud ``sqlite3.IntegrityError`` rather than a contract violation.
    """
    for null_field in ("volume_id", "volume_offset"):
        with CaseStore.create(case_dir / null_field) as store:
            source_id = _seed_evidence_source(store)
            bad = FileRow(
                evidence_source_id=source_id,
                volume_id=0,
                volume_offset=0,
                path="/x",
                name="x",
                meta_addr=1,
                allocated=True,
            )
            # Force the NULL the model type forbids to prove the DB rejects it.
            object.__setattr__(bad, null_field, None)
            with pytest.raises(sqlite3.IntegrityError):
                store.insert_file(bad)


def test_volume_limitation_round_trips(case_dir: Path) -> None:
    """A D-20 VolumeLimitation finding round-trips equal."""
    with CaseStore.create(case_dir) as store:
        with store.transaction():
            source_id = _seed_evidence_source(store)
            lim_id = store.insert_volume_limitation(
                VolumeLimitation(
                    evidence_source_id=source_id,
                    volume_id=3,
                    volume_offset=2097152,
                    detected_desc="Linux (0x83)",
                    reason="Cannot determine file system type",
                    attributes={"encryption_hint": "likely LUKS"},
                )
            )
        loaded = store.get_volume_limitation(lim_id)
        all_for_source = store.get_volume_limitations(source_id)

    assert loaded.volume_id == 3
    assert loaded.volume_offset == 2097152
    assert loaded.detected_desc == "Linux (0x83)"
    assert loaded.reason == "Cannot determine file system type"
    assert loaded.attributes == {"encryption_hint": "likely LUKS"}
    assert len(all_for_source) == 1


def test_log_finding_round_trips(case_dir: Path) -> None:
    """A D-44/D-45 LogFinding round-trips equal (mirrors VolumeLimitation)."""
    with CaseStore.create(case_dir) as store:
        with store.transaction():
            source_id = _seed_evidence_source(store)
            n = store.insert_log_findings(
                [
                    LogFinding(
                        evidence_source_id=source_id,
                        category="tamperability",
                        subject="/home/alice/.bash_history",
                        detail="shell history is editable by the subject",
                        attributes={"kind": "bash"},
                    )
                ]
            )
        loaded = store.get_log_findings(source_id)

    assert n == 1
    assert len(loaded) == 1
    finding = loaded[0]
    assert finding.category == "tamperability"
    assert finding.subject == "/home/alice/.bash_history"
    assert finding.detail == "shell history is editable by the subject"
    assert finding.attributes == {"kind": "bash"}
    assert finding.id is not None


def test_get_log_findings_orders_by_id_and_empty_for_none(case_dir: Path) -> None:
    """get_log_findings returns insertion (id) order and [] for a bare source."""
    with CaseStore.create(case_dir) as store:
        with store.transaction():
            source_id = _seed_evidence_source(store)
            other_id = store.insert_evidence_source(
                EvidenceSource(
                    case_id=store.get_evidence_source(source_id).case_id,
                    evidence_id="EV-2",
                    path="/y.dd",
                    image_type="raw",
                )
            )
            store.insert_log_findings(
                [
                    LogFinding(
                        evidence_source_id=source_id,
                        category="completeness",
                        subject="auth.log",
                        detail="reassembled oldest->newest",
                    ),
                    LogFinding(
                        evidence_source_id=source_id,
                        category="tamperability",
                        subject="/root/.bash_history",
                        detail="editable; not chronological truth",
                    ),
                ]
            )
        ordered = store.get_log_findings(source_id)
        empty = store.get_log_findings(other_id)

    # Insertion (store-owned id) order, NOT category/subject sort (D-41).
    assert [f.category for f in ordered] == ["completeness", "tamperability"]
    assert empty == []


def test_insert_log_findings_composes_in_outer_transaction(case_dir: Path) -> None:
    """insert_log_findings defers its commit to the outer transaction (WR-01)."""
    with CaseStore.create(case_dir) as store:
        with store.transaction():
            source_id = _seed_evidence_source(store)
            store.insert_log_findings(
                [
                    LogFinding(
                        evidence_source_id=source_id,
                        category="tamperability",
                        subject="/home/bob/.zsh_history",
                        detail="editable",
                    )
                ]
            )
            # Still inside the outer transaction: a sibling connection must not
            # see the row yet (the insert did not prematurely commit).
            sibling = sqlite3.connect(case_dir / "case.db")
            try:
                sibling.execute("PRAGMA busy_timeout = 200")
                count = sibling.execute(
                    "SELECT COUNT(*) FROM log_findings"
                ).fetchone()[0]
            finally:
                sibling.close()
            assert count == 0
        # After the outer commit the row is visible.
        assert len(store.get_log_findings(source_id)) == 1


def _seed_timeline_event(
    source_id: int, ts_utc: str, event_type: str, **overrides: object
) -> TimelineEvent:
    """Build a minimal :class:`TimelineEvent` with sensible defaults for tests."""
    base: dict[str, object] = {
        "evidence_source_id": source_id,
        "ts_utc": ts_utc,
        "source": "filesystem:ext4",
        "event_type": event_type,
        "volume_id": 0,
        "volume_offset": 0,
        "path": "/x",
        "meta_addr": 11,
    }
    base.update(overrides)
    return TimelineEvent(**base)  # type: ignore[arg-type]


def test_timeline_events_table_and_indexes_exist(case_dir: Path) -> None:
    """A fresh case.db carries the timeline_events table + both D-26 indexes."""
    with CaseStore.create(case_dir) as store:
        cols = {
            row[1]
            for row in store.connection.execute(
                "PRAGMA table_info(timeline_events)"
            ).fetchall()
        }
        assert cols, "timeline_events table missing from a fresh case.db"
        assert "attributes" in cols
        indexes = {
            row[1]
            for row in store.connection.execute(
                "PRAGMA index_list(timeline_events)"
            ).fetchall()
        }
    assert "idx_timeline_events_order" in indexes
    assert "idx_timeline_events_evidence_source_id" in indexes


def test_timeline_event_round_trips(case_dir: Path) -> None:
    """A TimelineEvent persists via the bulk insert and reads back equal."""
    with CaseStore.create(case_dir) as store:
        with store.transaction():
            source_id = _seed_evidence_source(store)
            n = store.insert_timeline_events(
                [
                    _seed_timeline_event(
                        source_id,
                        "2026-01-01T00:00:00+00:00",
                        "modified",
                        actor="uid=0,gid=0",
                        file_id=None,
                        attributes={"k": "v"},
                    )
                ]
            )
        events = store.get_timeline_events(source_id)

    assert n == 1
    assert len(events) == 1
    event = events[0]
    assert event.ts_utc == "2026-01-01T00:00:00+00:00"
    assert event.event_type == "modified"
    assert event.source == "filesystem:ext4"
    assert event.volume_id == 0
    assert event.volume_offset == 0
    assert event.path == "/x"
    assert event.meta_addr == 11
    assert event.actor == "uid=0,gid=0"
    assert event.attributes == {"k": "v"}
    assert event.id is not None


def test_get_timeline_events_applies_d26_total_order(case_dir: Path) -> None:
    """get_timeline_events imposes the D-26 total order regardless of insert order.

    The fixture deliberately ties events on ts_utc + volume_id + volume_offset +
    path so the ``event_type`` and ``meta_addr`` tiebreaks are each exercised:
    dropping either key flips an adjacent pair and fails this assertion.
    """
    ts = "2026-01-01T00:00:00+00:00"
    with CaseStore.create(case_dir) as store:
        with store.transaction():
            source_id = _seed_evidence_source(store)
            # Insert in a deliberately scrambled order.
            store.insert_timeline_events(
                [
                    # later timestamp, should sort last
                    _seed_timeline_event(
                        source_id, "2026-02-02T00:00:00+00:00", "born",
                        path="/a", meta_addr=1,
                    ),
                    # ties on ts/vol/offset/path with the next; differs on type
                    _seed_timeline_event(
                        source_id, ts, "modified", path="/a", meta_addr=5,
                    ),
                    _seed_timeline_event(
                        source_id, ts, "changed", path="/a", meta_addr=5,
                    ),
                    # same ts/type/path but different meta_addr — meta_addr tiebreak
                    _seed_timeline_event(
                        source_id, ts, "changed", path="/a", meta_addr=2,
                    ),
                ]
            )
        events = store.get_timeline_events(source_id)

    observed = [(e.ts_utc, e.path, e.event_type, e.meta_addr) for e in events]
    assert observed == [
        # event_type 'changed' < 'modified' lexicographically; within 'changed'
        # meta_addr 2 < 5 — both tiebreaks gate distinct adjacent pairs.
        (ts, "/a", "changed", 2),
        (ts, "/a", "changed", 5),
        (ts, "/a", "modified", 5),
        ("2026-02-02T00:00:00+00:00", "/a", "born", 1),
    ]


def test_get_timeline_events_limit(case_dir: Path) -> None:
    """The optional limit returns only the first N events in D-26 order."""
    with CaseStore.create(case_dir) as store:
        with store.transaction():
            source_id = _seed_evidence_source(store)
            store.insert_timeline_events(
                [
                    _seed_timeline_event(
                        source_id, f"2026-01-0{i}T00:00:00+00:00", "modified",
                        path="/a", meta_addr=i,
                    )
                    for i in range(1, 6)
                ]
            )
        first_two = store.get_timeline_events(source_id, limit=2)

    assert [e.ts_utc for e in first_two] == [
        "2026-01-01T00:00:00+00:00",
        "2026-01-02T00:00:00+00:00",
    ]


def test_schema_has_attributes_column_on_every_table(case_dir: Path) -> None:
    """Each table carries a JSON ``attributes`` column (blackboard pattern)."""
    with CaseStore.create(case_dir) as store:
        for table in (
            "cases",
            "evidence_sources",
            "run_log",
            "files",
            "volume_limitations",
            "timeline_events",
            "log_findings",
        ):
            cols = {
                row[1]
                for row in store.connection.execute(
                    f"PRAGMA table_info({table})"
                ).fetchall()
            }
            assert "attributes" in cols, f"{table} missing attributes column"


def test_attributes_stored_as_json_text(case_dir: Path) -> None:
    """The attributes column is serialized JSON text in the DB."""
    with CaseStore.create(case_dir) as store:
        case_id = store.insert_case(
            Case(name="c", examiner="ex", attributes={"k": "v"})
        )
        raw = store.connection.execute(
            "SELECT attributes FROM cases WHERE id = ?", (case_id,)
        ).fetchone()[0]
    assert json.loads(raw) == {"k": "v"}


def test_unknown_case_raises(case_dir: Path) -> None:
    """Reading a missing case raises a specific lookup error."""
    with CaseStore.create(case_dir) as store:
        with pytest.raises(LookupError):
            store.get_case(99999)


def test_evidence_foreign_key_enforced(case_dir: Path) -> None:
    """Inserting evidence for a non-existent case violates the FK."""
    with CaseStore.create(case_dir) as store:
        with pytest.raises(sqlite3.IntegrityError):
            store.insert_evidence_source(
                EvidenceSource(
                    case_id=4242,
                    evidence_id="EV",
                    path="/x.dd",
                    image_type="raw",
                )
            )


def test_transaction_commits_both_rows_atomically(case_dir: Path) -> None:
    """A clean transaction commits the case + evidence rows together (WR-01)."""
    with CaseStore.create(case_dir) as store:
        with store.transaction():
            case_id = store.insert_case(Case(name="c", examiner="ex"))
            store.insert_evidence_source(
                EvidenceSource(
                    case_id=case_id,
                    evidence_id="EV",
                    path="/x.dd",
                    image_type="raw",
                )
            )
        cases = store.connection.execute("SELECT COUNT(*) FROM cases").fetchone()[
            0
        ]
        sources = store.connection.execute(
            "SELECT COUNT(*) FROM evidence_sources"
        ).fetchone()[0]
    assert cases == 1
    assert sources == 1


def test_transaction_rolls_back_on_exception(case_dir: Path) -> None:
    """An exception inside a transaction rolls back the case row (WR-01)."""
    with CaseStore.create(case_dir) as store:
        with pytest.raises(RuntimeError):
            with store.transaction():
                store.insert_case(Case(name="c", examiner="ex"))
                raise RuntimeError("boom before evidence insert")
        # The committed-row count is read on a fresh connection to confirm the
        # rollback was durable, not merely uncommitted in this connection.
        count = store.connection.execute(
            "SELECT COUNT(*) FROM cases"
        ).fetchone()[0]
    assert count == 0


def test_transaction_rejects_nesting(case_dir: Path) -> None:
    """Nested transactions are unsupported and raise (WR-01)."""
    with CaseStore.create(case_dir) as store:
        with pytest.raises(RuntimeError, match="nesting"):
            with store.transaction():
                with store.transaction():
                    pass


def test_schema_dataclass_mismatch_fails_loudly(tmp_path: Path) -> None:
    """A model/table drift is refused at the seam, not silently absorbed.

    The mapping is derived from the dataclasses, so a table missing a column
    the model declares must fail where it is detectable. Silently dropping the
    column would mean every row the store returns is quietly incomplete — the
    worst possible failure mode for an evidence store.
    """
    from pyautopsy.case.mapping import RowMapper, validate_mapping  # noqa: PLC0415
    from pyautopsy.case.models import KnownMatch  # noqa: PLC0415

    case_dir = tmp_path / "case"
    CaseStore.create(case_dir).close()
    conn = sqlite3.connect(case_dir / "case.db")
    try:
        # A table that has lost a column the dataclass still declares.
        conn.execute("CREATE TABLE drifted (file_id INTEGER, source TEXT)")
        mapper: RowMapper[KnownMatch] = RowMapper(KnownMatch, "drifted")
        with pytest.raises(ValueError, match="mapping drift"):
            validate_mapping(mapper, conn)

        # And a table that does not exist at all.
        missing: RowMapper[KnownMatch] = RowMapper(KnownMatch, "no_such_table")
        with pytest.raises(ValueError, match="no table"):
            validate_mapping(missing, conn)
    finally:
        conn.close()


def test_allocated_distinguishes_none_from_false(case_dir: Path) -> None:
    """``allocated`` round-trips ``None`` (unknown) separately from ``False``.

    A deleted entry (``False``) and an entry whose allocation state could not be
    determined (``None``) are different forensic statements; storing a nullable
    bool as an integer must not collapse them.
    """
    store = CaseStore.create(case_dir)
    try:
        case_id = store.insert_case(Case(name="c", examiner="e"))
        source_id = store.insert_evidence_source(
            EvidenceSource(
                case_id=case_id,
                evidence_id="E1",
                path="/x.dd",
                image_type="raw",
                attributes={},
            )
        )
        for index, allocated in enumerate((True, False, None)):
            store.insert_file(
                FileRow(
                    evidence_source_id=source_id,
                    volume_id=0,
                    volume_offset=0,
                    path=f"/f{index}",
                    name=f"f{index}",
                    allocated=allocated,
                )
            )
        rows = store.get_files(source_id)
        assert [r.allocated for r in rows] == [True, False, None]
        # Not merely falsy-equal: the None must still BE None.
        assert rows[2].allocated is None
        assert rows[1].allocated is False
    finally:
        store.close()


def test_attributes_json_round_trips_with_sorted_keys(case_dir: Path) -> None:
    """``attributes`` serialises with sorted keys, so equal data is equal bytes.

    The reproducibility guarantee rests on this: two runs over the same image
    must produce byte-identical stored JSON regardless of dict insertion order.
    """
    store = CaseStore.create(case_dir)
    try:
        case_id = store.insert_case(Case(name="c", examiner="e"))
        source_id = store.insert_evidence_source(
            EvidenceSource(
                case_id=case_id,
                evidence_id="E1",
                path="/x.dd",
                image_type="raw",
                attributes={},
            )
        )
        payload = {"zebra": 1, "alpha": {"nested": True}, "middle": [1, 2, 3]}
        reordered = {"middle": [1, 2, 3], "zebra": 1, "alpha": {"nested": True}}
        ids = [
            store.insert_file(
                FileRow(
                    evidence_source_id=source_id,
                    volume_id=0,
                    volume_offset=0,
                    path=f"/f{i}",
                    name=f"f{i}",
                    attributes=attrs,
                )
            )
            for i, attrs in enumerate((payload, reordered))
        ]
        stored = [
            row["attributes"]
            for row in store.connection.execute(
                "SELECT attributes FROM files WHERE id IN (?, ?) ORDER BY id", ids
            )
        ]
        assert stored[0] == stored[1], "key order leaked into the stored JSON"
        assert stored[0] == json.dumps(payload, sort_keys=True)
        assert store.get_file(ids[0]).attributes == payload
    finally:
        store.close()


def test_search_hit_term_round_trips_non_utf8_bytes(case_dir: Path) -> None:
    """A non-UTF-8 search needle survives storage byte-for-byte."""
    store = CaseStore.create(case_dir)
    try:
        case_id = store.insert_case(Case(name="c", examiner="e"))
        source_id = store.insert_evidence_source(
            EvidenceSource(
                case_id=case_id,
                evidence_id="E1",
                path="/x.dd",
                image_type="raw",
                attributes={},
            )
        )
        needle = b"\xff\xfe\x00binary-needle\x80"
        store.insert_search_hits(
            [
                SearchHit(
                    evidence_source_id=source_id,
                    region="unallocated",
                    term=needle,
                    term_kind="literal",
                    volume_id=0,
                    volume_offset=0,
                    byte_offset=512,
                )
            ]
        )
        assert store.get_search_hits(source_id)[0].term == needle
    finally:
        store.close()
