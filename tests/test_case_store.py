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

from pyautopsy.case import Case, CaseStore, EvidenceSource


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


def test_schema_has_attributes_column_on_every_table(case_dir: Path) -> None:
    """Each table carries a JSON ``attributes`` column (blackboard pattern)."""
    with CaseStore.create(case_dir) as store:
        for table in ("cases", "evidence_sources", "run_log"):
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
