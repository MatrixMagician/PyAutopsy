"""End-to-end ``pyautopsy ingest`` smoke + CLI-surface tests (D-12).

This is the Walking-Skeleton finish line for Phase 1: invoking the exact D-12 CLI
signature must exit 0 and create the case store (``case.db``) and the audit log
(``logs/audit.jsonl``) under the case directory. Plan 01-04 implements the
``ingest`` command, so the original ``xfail(strict=True)`` marker is **removed**
here and the test now asserts the real contract.

Alongside the happy-path smoke test, this module checks the CLI's loud-failure
and help behaviors: a wrong ``--acquisition-hash`` exits non-zero with a FAIL
audit event (D-08), ``--help`` lists the documented options, and a missing
required option errors clearly (Typer validation).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from typer.testing import CliRunner

from pyautopsy.cli.main import app

runner = CliRunner()


def _ingest_args(image: Path, case: Path, *, acquisition_hash: str | None = None):
    """Build the D-12 ``ingest`` argument vector."""
    args = [
        "ingest",
        str(image),
        "--case",
        str(case),
        "--examiner",
        "X",
        "--evidence-id",
        "E1",
    ]
    if acquisition_hash is not None:
        args += ["--acquisition-hash", acquisition_hash]
    return args


def test_ingest_smoke(tiny_raw_image: Path, case_dir: Path) -> None:
    """`pyautopsy ingest <img> --case <dir> --examiner X --evidence-id E1` works.

    Asserts exit 0 and that the case store + audit log are created — the
    Walking-Skeleton contract that was xfail-pinned by plan 01-00.
    """
    result = runner.invoke(app, _ingest_args(tiny_raw_image, case_dir))

    assert result.exit_code == 0, result.output
    assert (case_dir / "case.db").is_file()
    assert (case_dir / "logs" / "audit.jsonl").is_file()


def test_ingest_acquisition_match_exits_zero(
    tiny_raw_image: Path, case_dir: Path
) -> None:
    """A correct ``--acquisition-hash`` still exits 0."""
    sha256 = hashlib.sha256(tiny_raw_image.read_bytes()).hexdigest()
    result = runner.invoke(
        app, _ingest_args(tiny_raw_image, case_dir, acquisition_hash=sha256)
    )
    assert result.exit_code == 0, result.output


def test_ingest_wrong_acquisition_hash_exits_nonzero(
    tiny_raw_image: Path, case_dir: Path
) -> None:
    """A wrong ``--acquisition-hash`` exits non-zero + records a FAIL event."""
    result = runner.invoke(
        app, _ingest_args(tiny_raw_image, case_dir, acquisition_hash="0" * 64)
    )
    assert result.exit_code != 0

    log = case_dir / "logs" / "audit.jsonl"
    events = [
        json.loads(line)
        for line in log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    compare = next(
        e for e in events if e["action"] == "ingest.acquisition_compare"
    )
    assert compare["outcome"] == "FAIL"


def test_ingest_help_lists_documented_options() -> None:
    """``ingest --help`` lists every D-12 option."""
    result = runner.invoke(app, ["ingest", "--help"])
    assert result.exit_code == 0
    for option in ("--case", "--examiner", "--evidence-id", "--acquisition-hash"):
        assert option in result.output


def test_ingest_missing_required_option_errors(
    tiny_raw_image: Path,
) -> None:
    """Omitting a required option errors clearly (non-zero, Typer validation)."""
    result = runner.invoke(app, ["ingest", str(tiny_raw_image)])
    assert result.exit_code != 0


def test_version_flag() -> None:
    """``pyautopsy --version`` prints the package version and exits 0."""
    import pyautopsy

    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert pyautopsy.__version__ in result.output
