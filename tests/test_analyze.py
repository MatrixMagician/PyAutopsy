"""RED Wave-0 scaffold for the single-command ``analyze`` pipeline (CLI-01).

Covers the exact pytest node IDs from 03-RESEARCH.md "Phase Requirements ->
Test Map" (lines 504-505): ``analyze`` exits 0 and writes the report set, and
``analyze`` composes ingest+walk+timeline with the end-of-run re-verify. They
drive the ``analyze`` Typer command + ``pyautopsy.core.analyze.run_analyze``
through a ``CliRunner`` (mirroring test_reproducibility.py / test_cli_smoke.py),
so each is collected and RED until Waves 1+ land.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from pyautopsy.cli.main import app

runner = CliRunner()


def _analyze(image: Path, case: Path) -> None:
    """Run ``pyautopsy analyze`` once into ``case``; assert it exits 0."""
    result = runner.invoke(
        app,
        [
            "analyze",
            str(image),
            "--case",
            str(case),
            "--examiner",
            "X",
            "--evidence-id",
            "E1",
        ],
    )
    assert result.exit_code == 0, result.output


def test_analyze_produces_reports(tiny_ext4_image: Path, tmp_path: Path) -> None:
    """``analyze`` writes reports/report.html + report.json + run_metadata.json."""
    case = tmp_path / "case"
    _analyze(tiny_ext4_image, case)

    assert (case / "reports" / "report.html").is_file()
    assert (case / "reports" / "report.json").is_file()
    assert (case / "reports" / "run_metadata.json").is_file()


def test_analyze_composes_pipeline(tiny_ext4_image: Path, tmp_path: Path) -> None:
    """``analyze`` composes ingest+walk+timeline and re-verifies the source.

    COC rows (cases + evidence_sources), files, and timeline_events are all
    present after one command; the end-of-run source-hash re-verify ran (its
    PASS is recorded in the audit log, like ingest/walk).
    """
    case = tmp_path / "case"
    _analyze(tiny_ext4_image, case)

    conn = sqlite3.connect(case / "case.db")
    conn.row_factory = sqlite3.Row
    try:
        cases = conn.execute("SELECT COUNT(*) AS n FROM cases").fetchone()["n"]
        sources = conn.execute("SELECT COUNT(*) AS n FROM evidence_sources").fetchone()[
            "n"
        ]
        files = conn.execute("SELECT COUNT(*) AS n FROM files").fetchone()["n"]
        events = conn.execute("SELECT COUNT(*) AS n FROM timeline_events").fetchone()[
            "n"
        ]
    finally:
        conn.close()

    assert cases == 1
    assert sources == 1
    assert files > 0
    assert events > 0

    # The end-of-run re-verify is audited like ingest/walk (REPORT-02).
    audit = (case / "logs" / "audit.jsonl").read_text(encoding="utf-8")
    assert "verify" in audit


def test_analyze_closes_every_store_it_opens(
    tiny_ext4_image: Path, tmp_path: Path, monkeypatch
) -> None:
    """``run_analyze`` leaks no database connection (CR-03).

    The pipeline opens a store for the report read-back on top of the ones its
    sub-orchestrators open. Every one must be closed on the way out: an unclosed
    SQLite handle keeps a WAL open against the case database, and a long-lived
    caller running many cases accumulates them until it hits the process
    file-descriptor limit.

    sqlite releases the handle at interpreter exit, so this is invisible to a
    test that merely asserts the run succeeded. Stores are tagged with a
    monotonic counter rather than ``id()``, because CPython reuses the address
    of a collected object and a leaked store would masquerade as a closed one.
    """
    import itertools  # noqa: PLC0415

    from pyautopsy.case import store as store_mod  # noqa: PLC0415
    from pyautopsy.core.analyze import run_analyze  # noqa: PLC0415

    tags = itertools.count(1)
    opened: list[int] = []
    closed: list[int] = []

    original_open = store_mod.CaseStore.open.__func__
    original_create = store_mod.CaseStore.create.__func__
    original_close = store_mod.CaseStore.close

    def tag(store: object) -> object:
        store._tracking_tag = next(tags)  # type: ignore[attr-defined]
        opened.append(store._tracking_tag)  # type: ignore[attr-defined]
        return store

    @classmethod  # type: ignore[misc]
    def tracked_open(cls: type, case_dir: Path) -> object:
        return tag(original_open(cls, case_dir))

    @classmethod  # type: ignore[misc]
    def tracked_create(cls: type, case_dir: Path) -> object:
        return tag(original_create(cls, case_dir))

    def tracked_close(self: object) -> None:
        tag_value = getattr(self, "_tracking_tag", None)
        if tag_value is not None:
            closed.append(tag_value)
        original_close(self)

    monkeypatch.setattr(store_mod.CaseStore, "open", tracked_open)
    monkeypatch.setattr(store_mod.CaseStore, "create", tracked_create)
    monkeypatch.setattr(store_mod.CaseStore, "close", tracked_close)

    run_analyze(
        tiny_ext4_image,
        tmp_path / "case",
        examiner="X",
        evidence_id="E1",
    )

    leaked = [tag_value for tag_value in opened if tag_value not in closed]
    assert not leaked, (
        f"{len(leaked)} of {len(opened)} case stores opened by run_analyze were "
        f"never closed (tags {leaked})"
    )
