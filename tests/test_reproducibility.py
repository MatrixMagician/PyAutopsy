"""Reproducibility seed for Phase-3 CLI-02 (PITFALLS P3 / D-08).

Two ingests of the same fixture into separate case directories must produce
**byte-identical analytical content** — the evidence digests (sha256/md5), byte
size, image type, and the deterministically-ordered chain-of-custody fields —
while run-only metadata (creation/acquisition timestamps) is segregated and
deliberately excluded from the comparison.

This pins the determinism bar the single-command ``analyze`` pipeline must meet
in Phase 3: analytical output is a pure function of the evidence, not of when the
tool ran.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from pyautopsy.cli.main import app

runner = CliRunner()

# Columns that are wall-clock / run metadata, segregated from analytical content
# and therefore excluded from the cross-run comparison (PITFALLS P3).
_RUN_METADATA_COLUMNS = {"created_utc", "acquired_utc"}


def _ingest(image: Path, case: Path) -> None:
    """Run ``pyautopsy ingest`` once into ``case``; assert it exits 0."""
    result = runner.invoke(
        app,
        [
            "ingest",
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


def _analytical_fields(case_dir: Path) -> dict[str, object]:
    """Extract the analytical (reproducible) evidence + case fields.

    Wall-clock / run metadata columns are dropped so the comparison reflects only
    content derived from the evidence itself.
    """
    conn = sqlite3.connect(case_dir / "case.db")
    conn.row_factory = sqlite3.Row
    try:
        case = dict(conn.execute("SELECT * FROM cases ORDER BY id").fetchone())
        ev = dict(
            conn.execute(
                "SELECT * FROM evidence_sources ORDER BY id"
            ).fetchone()
        )
    finally:
        conn.close()

    analytical: dict[str, object] = {}
    for prefix, row in (("case", case), ("evidence", ev)):
        for key, value in row.items():
            if key in _RUN_METADATA_COLUMNS or key == "id" or key == "case_id":
                continue
            analytical[f"{prefix}.{key}"] = value
    return analytical


def test_two_runs_produce_identical_analytical_content(
    tiny_raw_image: Path, tmp_path: Path
) -> None:
    """Two ingests of the same fixture share byte-identical analytical fields."""
    case_a = tmp_path / "case_a"
    case_b = tmp_path / "case_b"

    _ingest(tiny_raw_image, case_a)
    _ingest(tiny_raw_image, case_b)

    fields_a = _analytical_fields(case_a)
    fields_b = _analytical_fields(case_b)

    assert fields_a == fields_b
    # Sanity: the digests are actually present and compared (not an empty dict).
    assert fields_a["evidence.sha256"]
    assert fields_a["evidence.md5"]
    assert fields_a["evidence.byte_size"]
    assert fields_a["evidence.image_type"] == "raw"


def test_run_metadata_is_segregated(
    tiny_raw_image: Path, tmp_path: Path
) -> None:
    """Run metadata (timestamps) is stored but excluded from the comparison.

    Both runs persist a ``created_utc``/``acquired_utc`` (run metadata exists),
    yet those columns are intentionally not part of the analytical comparison —
    demonstrating the segregation that keeps analytical output reproducible.
    """
    case_a = tmp_path / "case_a"
    _ingest(tiny_raw_image, case_a)

    conn = sqlite3.connect(case_a / "case.db")
    conn.row_factory = sqlite3.Row
    try:
        case = conn.execute("SELECT created_utc FROM cases").fetchone()
        ev = conn.execute("SELECT acquired_utc FROM evidence_sources").fetchone()
    finally:
        conn.close()

    # Run metadata is present and UTC, but lives outside the analytical set.
    assert case["created_utc"].endswith("+00:00")
    assert ev["acquired_utc"].endswith("+00:00")
    assert "case.created_utc" not in _analytical_fields(case_a)
    assert "evidence.acquired_utc" not in _analytical_fields(case_a)
