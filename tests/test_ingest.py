"""Behavior suite for the ingest orchestrator (``core.ingest.run_ingest``).

These tests drive the real orchestrator over the committed deterministic
``tiny_raw.dd`` fixture into a ``tmp_path`` case directory and assert every
orchestration behavior from plan 01-04 Task 1: read-only open, single-pass
MD5+SHA-256 with end-of-run re-verify, ``cases`` + ``evidence_sources`` COC rows,
the JSONL audit trail (start→end including the integrity outcome), output
confined to the case dir, the case-dir/evidence separation guard (D-01), the
mounted-source guard (P1), and the acquisition-hash PASS/FAIL path (D-08).

They map directly to 01-VALIDATION.md rows 1-04-01 (COC persistence) and
1-04-02 (audit log).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from pyautopsy.core.ingest import IngestError, IngestResult, run_ingest
from pyautopsy.evidence import integrity
from pyautopsy.evidence.integrity import IntegrityError, MountedSourceError


def _read_audit(case_dir: Path) -> list[dict]:
    """Return the parsed audit-log events for a completed ingest."""
    log = case_dir / "logs" / "audit.jsonl"
    return [
        json.loads(line)
        for line in log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _actions(events: list[dict]) -> list[str]:
    """Return the ordered ``action`` names of audit events."""
    return [event["action"] for event in events]


def _expected_digests(image: Path) -> dict[str, str]:
    """Compute the reference MD5+SHA-256 of the fixture with stdlib hashlib."""
    data = image.read_bytes()
    return {
        "md5": hashlib.md5(data).hexdigest(),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


# -- happy path: orchestration + COC persistence (row 1-04-01) -------------


def test_run_ingest_persists_case_and_evidence_rows(
    tiny_raw_image: Path, case_dir: Path
) -> None:
    """A full run persists a ``cases`` row + an ``evidence_sources`` row."""
    result = run_ingest(
        tiny_raw_image,
        case_dir,
        examiner="Dana Examiner",
        evidence_id="E1",
    )

    assert isinstance(result, IngestResult)
    assert result.success is True

    expected = _expected_digests(tiny_raw_image)
    conn = sqlite3.connect(case_dir / "case.db")
    conn.row_factory = sqlite3.Row
    try:
        case = conn.execute("SELECT * FROM cases").fetchone()
        assert case is not None
        assert case["examiner"] == "Dana Examiner"
        assert case["pyautopsy_version"]
        assert case["created_utc"].endswith("+00:00")

        ev = conn.execute("SELECT * FROM evidence_sources").fetchone()
        assert ev is not None
        assert ev["case_id"] == case["id"]
        assert ev["evidence_id"] == "E1"
        assert ev["image_type"] == "raw"
        assert ev["sha256"] == expected["sha256"]
        assert ev["md5"] == expected["md5"]
        assert ev["byte_size"] == tiny_raw_image.stat().st_size
        assert ev["tsk_version"]
        assert ev["acquired_utc"].endswith("+00:00")
    finally:
        conn.close()

    # The result echoes the analytical digests for the caller (CLI summary).
    assert result.sha256 == expected["sha256"]
    assert result.md5 == expected["md5"]
    assert result.byte_size == tiny_raw_image.stat().st_size


def test_run_ingest_computes_md5_and_sha256(
    tiny_raw_image: Path, case_dir: Path
) -> None:
    """Both MD5 and SHA-256 are computed and match a hashlib reference."""
    result = run_ingest(tiny_raw_image, case_dir, examiner="X", evidence_id="E1")
    expected = _expected_digests(tiny_raw_image)
    assert result.md5 == expected["md5"]
    assert result.sha256 == expected["sha256"]


# -- audit trail start→end incl. re-verify (row 1-04-02) -------------------


def test_run_ingest_writes_start_to_end_audit_trail(
    tiny_raw_image: Path, case_dir: Path
) -> None:
    """The audit log records start, open, hash, re-verify, and end events."""
    run_ingest(tiny_raw_image, case_dir, examiner="X", evidence_id="E1")
    actions = _actions(_read_audit(case_dir))

    # Start is first, end is last, and the integrity-bearing actions appear.
    assert actions[0] == "ingest.start"
    assert actions[-1] == "ingest.end"
    for required in ("ingest.open", "ingest.hash", "ingest.reverify"):
        assert required in actions, f"missing audit action {required}: {actions}"


def test_run_ingest_records_hashes_in_audit_log(
    tiny_raw_image: Path, case_dir: Path
) -> None:
    """The hash event records both digests and the byte size (REPORT-02)."""
    run_ingest(tiny_raw_image, case_dir, examiner="X", evidence_id="E1")
    events = _read_audit(case_dir)
    expected = _expected_digests(tiny_raw_image)
    hash_event = next(e for e in events if e["action"] == "ingest.hash")
    assert hash_event["sha256"] == expected["sha256"]
    assert hash_event["md5"] == expected["md5"]


# -- read-only guarantee (INGEST-01/03) -----------------------------------


def test_run_ingest_leaves_source_unchanged(
    tiny_raw_image: Path, case_dir: Path
) -> None:
    """The source image mtime + size are unchanged after a full run."""
    before = tiny_raw_image.stat()
    run_ingest(tiny_raw_image, case_dir, examiner="X", evidence_id="E1")
    after = tiny_raw_image.stat()
    assert after.st_size == before.st_size
    assert after.st_mtime_ns == before.st_mtime_ns


# -- output confinement (D-01 / P11) --------------------------------------


def test_run_ingest_confines_output_to_case_dir(
    tiny_raw_image: Path, case_dir: Path
) -> None:
    """``case.db`` + ``logs/audit.jsonl`` exist under the case dir only."""
    run_ingest(tiny_raw_image, case_dir, examiner="X", evidence_id="E1")
    assert (case_dir / "case.db").is_file()
    assert (case_dir / "logs" / "audit.jsonl").is_file()
    # Nothing was written next to the evidence.
    evidence_siblings = {p.name for p in tiny_raw_image.parent.iterdir()}
    assert "case.db" not in evidence_siblings
    assert "audit.jsonl" not in evidence_siblings


# -- case-dir / evidence separation guard (D-01) --------------------------


def test_run_ingest_rejects_case_dir_inside_evidence(
    tiny_raw_image: Path,
) -> None:
    """A case dir under the evidence directory is rejected before any work."""
    overlapping = tiny_raw_image.parent / "case_inside"
    with pytest.raises(IngestError):
        run_ingest(
            tiny_raw_image,
            overlapping,
            examiner="X",
            evidence_id="E1",
        )


def test_run_ingest_rejects_case_dir_equal_to_evidence_parent(
    tiny_raw_image: Path,
) -> None:
    """A case dir equal to the evidence's directory is rejected (D-01)."""
    with pytest.raises(IngestError):
        run_ingest(
            tiny_raw_image,
            tiny_raw_image.parent,
            examiner="X",
            evidence_id="E1",
        )


# -- mounted-source guard (P1) --------------------------------------------


def test_run_ingest_refuses_mounted_source(
    tiny_raw_image: Path, case_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mounted-source path is refused (delegates to integrity guard)."""

    def _refuse(path: object, mounts_text: str | None = None) -> None:
        raise MountedSourceError("mounted source (injected)")

    monkeypatch.setattr(integrity, "assert_source_not_mounted", _refuse)
    with pytest.raises(MountedSourceError):
        run_ingest(tiny_raw_image, case_dir, examiner="X", evidence_id="E1")


# -- acquisition-hash compare PASS/FAIL (D-08) ----------------------------


def test_run_ingest_acquisition_hash_pass(
    tiny_raw_image: Path, case_dir: Path
) -> None:
    """A matching ``acquisition_hash`` records a PASS and succeeds."""
    expected = _expected_digests(tiny_raw_image)
    result = run_ingest(
        tiny_raw_image,
        case_dir,
        examiner="X",
        evidence_id="E1",
        acquisition_hash=expected["sha256"],
    )
    assert result.success is True
    events = _read_audit(case_dir)
    compare = next(e for e in events if e["action"] == "ingest.acquisition_compare")
    assert compare["outcome"] == "PASS"


def test_run_ingest_acquisition_hash_mismatch_raises_and_audits_fail(
    tiny_raw_image: Path, case_dir: Path
) -> None:
    """A wrong ``acquisition_hash`` raises IntegrityError + FAIL audit event."""
    bad = "0" * 64
    with pytest.raises(IntegrityError):
        run_ingest(
            tiny_raw_image,
            case_dir,
            examiner="X",
            evidence_id="E1",
            acquisition_hash=bad,
        )
    # The FAIL was recorded BEFORE the exception propagated (D-08).
    events = _read_audit(case_dir)
    compare = next(e for e in events if e["action"] == "ingest.acquisition_compare")
    assert compare["outcome"] == "FAIL"


# -- end-of-run re-verify mismatch (D-08 / INGEST-03) ---------------------


def test_run_ingest_reverify_mismatch_raises_and_audits_fail(
    tiny_raw_image: Path, case_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An injected end-of-run re-verify drift raises + records a FAIL event."""

    def _boom(source: object, baseline: dict[str, str]) -> None:
        raise IntegrityError("re-verify drift (injected)")

    monkeypatch.setattr(integrity, "reverify", _boom)
    with pytest.raises(IntegrityError):
        run_ingest(tiny_raw_image, case_dir, examiner="X", evidence_id="E1")

    events = _read_audit(case_dir)
    reverify = next(e for e in events if e["action"] == "ingest.reverify")
    assert reverify["outcome"] == "FAIL"
