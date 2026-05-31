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

import hashlib
import json
import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from pyautopsy.cli.main import app
from tests.fixtures import make_fixtures

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


def _analyze(image: Path, case: Path) -> None:
    """Run ``pyautopsy analyze`` once into ``case``; assert it exits 0.

    Mirrors :func:`_ingest` but drives the full single-command pipeline so the
    rendered report set (report.json/report.html + the run_metadata.json
    sidecar) is produced for the CLI-02 byte-identical comparison.
    """
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


def test_two_analyze_runs_byte_identical_report(
    tiny_ext4_image: Path, tmp_path: Path
) -> None:
    """CLI-02: two ``analyze`` runs produce byte-identical report.json AND report.html.

    Run-metadata placement is LOCKED to sidecar-only (W-1): ``report.html``
    carries ZERO run metadata, so BOTH report.json and report.html are compared
    whole-file with no footer-stripping. ``run_metadata.json`` is the single
    volatile file — excluded from the byte comparison and asserted to DIFFER
    (proving the segregation is real, not accidental equality).
    """
    case_a = tmp_path / "case_a"
    case_b = tmp_path / "case_b"

    _analyze(tiny_ext4_image, case_a)
    _analyze(tiny_ext4_image, case_b)

    json_a = (case_a / "reports" / "report.json").read_bytes()
    json_b = (case_b / "reports" / "report.json").read_bytes()
    html_a = (case_a / "reports" / "report.html").read_bytes()
    html_b = (case_b / "reports" / "report.html").read_bytes()

    # Heart of CLI-02: whole-file byte-equality on BOTH report.json and report.html.
    assert json_a == json_b
    assert html_a == html_b

    # Sanity: the body is non-empty and carries the fixture's timeline events —
    # guards against an empty-dict false pass (mirror the existing sanity guard).
    body_a = json.loads(json_a)
    assert body_a["timeline"], "expected the known file's timeline events"
    assert body_a["evidence"]["sha256"]

    # Negative assert: run_metadata.json IS present, carries a UTC generation
    # timestamp, and DOES differ between runs (segregation is real, W-1).
    meta_a = json.loads(
        (case_a / "reports" / "run_metadata.json").read_text(encoding="utf-8")
    )
    meta_b = json.loads(
        (case_b / "reports" / "run_metadata.json").read_text(encoding="utf-8")
    )
    assert meta_a["generated_utc"].endswith("+00:00")
    assert meta_a["generated_utc"] != meta_b["generated_utc"]


def _analyze_recover_filter(
    image: Path, case: Path, *, nsrl_db: Path, hash_set_allow: Path
) -> None:
    """Run ``analyze --recover --nsrl <db> --hash-set-allow <list>`` once.

    Drives the full INTEGRATION path (recovery + filtering opt-in, D-40) so the
    CLI-02/D-41 byte-identical comparison covers the recovered/orphan/known
    sections, not just the default pipeline.
    """
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
            "--recover",
            "--nsrl",
            str(nsrl_db),
            "--hash-set-allow",
            str(hash_set_allow),
        ],
    )
    assert result.exit_code == 0, result.output


def test_recover_filter_reproducible(
    ntfs_resident_deleted_image: Path,
    nsrl_minimal_db: Path,
    tmp_path: Path,
) -> None:
    """CLI-02/D-41: two ``analyze --recover --nsrl`` runs are byte-identical.

    Runs the full recover+filter analyze twice into ``case_a``/``case_b`` on the
    same NTFS resident-deleted fixture (which recovers a real intact file plus a
    separate orphan) and asserts:

    * ``report.json`` is whole-file byte-equal across runs (D-41), so the
      recovered/orphan/known sections carry no run-to-run drift; and
    * the SET of ``recovered/`` filenames is identical across runs — the
      deterministic ``vol/off/meta_addr`` naming has no wall-clock or
      enumeration-order leak (Pitfall 6).
    """
    # A custom allow-list whose single member is the recovered resident file's
    # md5 (UPPERCASE, as real RDS/hash sets store it) so the filtering pass
    # produces a real, deterministic custom match against a RECOVERED row.
    resident_md5 = hashlib.md5(make_fixtures.NTFS_RESIDENT_CONTENT).hexdigest()
    allow_list = tmp_path / "allow.txt"
    allow_list.write_text(
        f"{resident_md5.upper()}  resident-known\n", encoding="utf-8"
    )

    case_a = tmp_path / "case_a"
    case_b = tmp_path / "case_b"

    _analyze_recover_filter(
        ntfs_resident_deleted_image,
        case_a,
        nsrl_db=nsrl_minimal_db,
        hash_set_allow=allow_list,
    )
    _analyze_recover_filter(
        ntfs_resident_deleted_image,
        case_b,
        nsrl_db=nsrl_minimal_db,
        hash_set_allow=allow_list,
    )

    json_a = (case_a / "reports" / "report.json").read_bytes()
    json_b = (case_b / "reports" / "report.json").read_bytes()
    assert json_a == json_b

    # Sanity: the recover+filter path actually produced content (guards against
    # an empty-section false pass) — at least one recovered/orphan entry (this
    # fixture's resident file is recovered as a separate orphan) and the custom
    # allow-list matched the recovered resident row.
    body_a = json.loads(json_a)
    recovered_total = body_a["recovered"]["count"] + body_a["orphans"]["count"]
    assert recovered_total >= 1, "expected a recovered/orphan file"
    assert body_a["known"]["custom"]["count"] >= 1, "expected a custom match"

    def _recovered_names(case: Path) -> set[str]:
        recovered = case / "recovered"
        return {
            str(p.relative_to(recovered))
            for p in recovered.rglob("*")
            if p.is_file()
        }

    names_a = _recovered_names(case_a)
    names_b = _recovered_names(case_b)
    assert names_a, "expected recovered/ filenames to exist"
    assert names_a == names_b, "recovered/ filenames must be deterministic (D-41)"


def test_default_analyze_unchanged(
    tiny_ext4_image: Path, tmp_path: Path
) -> None:
    """D-40: a plain ``analyze`` (no recover/filter inputs) is byte-unchanged.

    Proves the opt-in wiring left the DEFAULT path untouched: a plain
    ``analyze`` (no ``--recover``/``--nsrl``/``--hash-set-*``) produces a
    ``report.json``/``report.html`` byte-identical to a second plain run — i.e.
    the Phase-3 baseline determinism still holds after the Phase-4 opt-in steps
    were spliced in. The MVP-limitations disclaimer also retains its verbatim
    default text (it must NOT mention that recovery/filtering ran, because they
    did not).
    """
    case_a = tmp_path / "case_a"
    case_b = tmp_path / "case_b"

    _analyze(tiny_ext4_image, case_a)
    _analyze(tiny_ext4_image, case_b)

    json_a = (case_a / "reports" / "report.json").read_bytes()
    json_b = (case_b / "reports" / "report.json").read_bytes()
    html_a = (case_a / "reports" / "report.html").read_bytes()
    html_b = (case_b / "reports" / "report.html").read_bytes()

    # D-40: the default path stays byte-identical across runs (no Phase-4 drift).
    assert json_a == json_b
    assert html_a == html_b

    # The default disclaimer is verbatim Phase-3 copy: it still asserts the
    # report does NOT include deleted-file recovery / NSRL filtering, because
    # neither ran on the default path (honesty without over/under-claim).
    body_a = json.loads(json_a)
    disclaimer = body_a["limitations"]["mvp_disclaimer"]
    assert "does NOT include deleted-file recovery" in disclaimer
    assert "known-file (NSRL) filtering" in disclaimer
    # And nothing was recovered/matched on the default path.
    assert body_a["recovered"]["count"] == 0
    assert body_a["known"]["custom"]["count"] == 0
    assert body_a["known"]["nsrl"]["count"] == 0
