"""RED Wave-0 scaffold for the deterministic reporter (REPORT-03 / REPORT-04).

Covers the exact pytest node IDs from 03-RESEARCH.md "Phase Requirements ->
Test Map" (lines 499-508): JSON body content, HTML autoescape of
evidence-controlled strings (Security V5), the D-27 truncation disclosure, the
D-28 findings (inventory + integrity + limitations), FAT provenance survival,
and recorded tool/TSK versions (CLI-02). They reference the planned
``pyautopsy.report`` package, so each is collected and RED until Waves 1+ land.
"""

from __future__ import annotations

from pathlib import Path

from pyautopsy.case import CaseStore
from pyautopsy.core.ingest import run_ingest
from pyautopsy.core.walk import run_walk
from pyautopsy.report.assemble import assemble_report_body
from pyautopsy.report.htmlreport import render_html
from pyautopsy.timeline.builder import build_timeline


def _analyzed_store(image: Path, case_dir: Path, *, timezone: str = "UTC") -> int:
    """Ingest + walk + build_timeline ``image`` into ``case_dir``; return source id."""
    ingested = run_ingest(image, case_dir, examiner="X", evidence_id="E1")
    run_walk(image, case_dir, timezone=timezone)
    with CaseStore.open(case_dir) as store:
        build_timeline(store, ingested.evidence_source_id)
    return ingested.evidence_source_id


def test_json_report(tiny_ext4_image: Path, case_dir: Path) -> None:
    """Assembled body carries COC, methodology+versions, findings, hashes, timeline."""
    source_id = _analyzed_store(tiny_ext4_image, case_dir)
    with CaseStore.open(case_dir) as store:
        body = assemble_report_body(store, source_id)

    assert "case" in body
    assert "evidence" in body
    assert "methodology" in body
    assert "findings" in body
    assert "timeline" in body
    # Full timeline lives in the JSON body (D-27), with a total count.
    assert isinstance(body["timeline"], list)
    assert body["timeline"], "expected the known file's events in the full timeline"
    assert body.get("timeline_total") == len(body["timeline"])
    # No volatile run metadata in the analytical body (D-25).
    assert "run_metadata" not in body
    assert "generated_utc" not in body


def test_html_autoescape(case_dir: Path) -> None:
    """A ``<script>``-bearing evidence string renders escaped, not as live markup."""
    from pyautopsy.case import Case, EvidenceSource, FileRow

    hostile = "/loot/<script>alert(1)</script>.txt"
    with CaseStore.create(case_dir) as store:
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
            store.insert_file(
                FileRow(
                    evidence_source_id=source_id,
                    volume_id=0,
                    volume_offset=0,
                    path=hostile,
                    name="<script>alert(1)</script>.txt",
                    meta_addr=11,
                    fs_type="ext4",
                    allocated=True,
                    mtime_utc="2026-01-01T00:00:00+00:00",
                )
            )
        build_timeline(store, source_id)
        body = assemble_report_body(store, source_id)
        html = render_html(body, case_dir)

    assert "&lt;script&gt;" in html
    assert "<script>alert(1)</script>" not in html


def test_html_truncation_note(case_dir: Path) -> None:
    """Events beyond the cap trigger an honest 'Showing N of M' disclosure (D-27)."""
    from pyautopsy.case import Case, EvidenceSource, FileRow

    with CaseStore.create(case_dir) as store:
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
            store.insert_files(
                [
                    FileRow(
                        evidence_source_id=source_id,
                        volume_id=0,
                        volume_offset=0,
                        path=f"/f{i}",
                        name=f"f{i}",
                        meta_addr=i,
                        fs_type="ext4",
                        allocated=True,
                        mtime_utc=f"2026-01-01T00:00:{i:02d}+00:00",
                    )
                    for i in range(5)
                ]
            )
        build_timeline(store, source_id)
        body = assemble_report_body(store, source_id)
        html = render_html(body, case_dir, cap=2)

    # Honest disclosure of the bounded view, full timeline in JSON (D-27).
    assert "Showing" in html
    assert "of 5" in html


def test_findings_d28(tiny_ext4_image: Path, case_dir: Path) -> None:
    """Findings = inventory stats + integrity PASS/FAIL + limitations (D-28)."""
    source_id = _analyzed_store(tiny_ext4_image, case_dir)
    with CaseStore.open(case_dir) as store:
        body = assemble_report_body(store, source_id)

    findings = body["findings"]
    assert "inventory" in findings
    assert "integrity" in findings
    assert "limitations" in findings
    # Inventory exposes counts that drive the honest summary (D-28).
    inventory = findings["inventory"]
    assert "file_count" in inventory
    assert "deleted_count" in inventory


def test_integrity_three_states_honest(
    tiny_ext4_image: Path, case_dir: Path
) -> None:
    """Integrity reflects the real acquisition outcome, never a hardcoded PASS (WR-02).

    No acquisition hash was supplied (default), so the body must surface the
    honest "not compared" state: acquisition_supplied False, the report does NOT
    claim a hash match (acquisition_compare_pass False), but the run is not a
    FAIL (passed True) and the copy never claims "source hash matches
    acquisition value". Supplying the verified outcome explicitly flips it to a
    real PASS; a FAIL outcome renders the FAIL copy.
    """
    source_id = _analyzed_store(tiny_ext4_image, case_dir)
    with CaseStore.open(case_dir) as store:
        # Default: no acquisition hash compared -> honest "not compared".
        not_compared = assemble_report_body(store, source_id)["integrity"]
        verified = assemble_report_body(
            store, source_id, acquisition_verified=True
        )["integrity"]
        failed = assemble_report_body(
            store, source_id, acquisition_verified=False
        )["integrity"]

    assert not_compared["acquisition_supplied"] is False
    assert not_compared["acquisition_compare_pass"] is False
    assert not_compared["passed"] is True
    assert "matches acquisition value" not in not_compared["copy"]
    assert "NOT COMPARED" in not_compared["copy"]

    assert verified["acquisition_supplied"] is True
    assert verified["acquisition_compare_pass"] is True
    assert verified["passed"] is True
    assert "PASS" in verified["copy"]

    assert failed["acquisition_supplied"] is True
    assert failed["passed"] is False
    assert "FAIL" in failed["copy"]


def test_fat_provenance(tiny_fat32_image: Path, case_dir: Path) -> None:
    """FAT local-time-inferred / assumed_timezone provenance survives to the report."""
    source_id = _analyzed_store(
        tiny_fat32_image, case_dir, timezone="America/New_York"
    )
    with CaseStore.open(case_dir) as store:
        body = assemble_report_body(store, source_id)

    serialized = repr(body)
    assert "local-time-inferred" in serialized
    assert "assumed_timezone" in serialized


def test_versions_recorded(tiny_ext4_image: Path, case_dir: Path) -> None:
    """tsk_version + pyautopsy_version appear in the report methodology (CLI-02)."""
    source_id = _analyzed_store(tiny_ext4_image, case_dir)
    with CaseStore.open(case_dir) as store:
        body = assemble_report_body(store, source_id)

    methodology = body["methodology"]
    assert methodology.get("pyautopsy_version")
    assert "tsk_version" in methodology
