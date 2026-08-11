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

import pytest
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
    compare = next(e for e in events if e["action"] == "ingest.acquisition_compare")
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


def test_walk_smoke_inventories_into_case(
    tiny_ext4_image: Path, case_dir: Path
) -> None:
    """`pyautopsy walk <img> --case <dir>` exits 0 and prints an inventory.

    Runs against a case created by a prior `ingest`, asserts exit 0 and that the
    summary reports inventoried files.
    """
    ingest = runner.invoke(app, _ingest_args(tiny_ext4_image, case_dir))
    assert ingest.exit_code == 0, ingest.output

    result = runner.invoke(app, ["walk", str(tiny_ext4_image), "--case", str(case_dir)])
    assert result.exit_code == 0, result.output
    assert "walk complete" in result.output
    assert "files inventoried:" in result.output


def test_walk_rejects_invalid_timezone(tiny_ext4_image: Path, case_dir: Path) -> None:
    """An invalid ``--timezone`` exits non-zero (Security V5 validation)."""
    runner.invoke(app, _ingest_args(tiny_ext4_image, case_dir))
    result = runner.invoke(
        app,
        [
            "walk",
            str(tiny_ext4_image),
            "--case",
            str(case_dir),
            "--timezone",
            "Not/AZone",
        ],
    )
    assert result.exit_code != 0


def test_walk_help_lists_options() -> None:
    """``walk --help`` lists the documented options."""
    result = runner.invoke(app, ["walk", "--help"])
    assert result.exit_code == 0
    for option in ("--case", "--timezone", "--max-hash-size"):
        assert option in result.output


def test_search_smoke_finds_term(
    log_search_image: Path, case_dir: Path, log_search_groundtruth: dict
) -> None:
    """`pyautopsy search <img> --case <dir> --term <needle>` exits 0 with hits.

    Runs against a case created by `ingest`, searches for the committed
    allocated needle, and asserts exit 0 + a deterministic hit-count summary.
    """
    ingest = runner.invoke(app, _ingest_args(log_search_image, case_dir))
    assert ingest.exit_code == 0, ingest.output

    needle = log_search_groundtruth["allocated_search"]["needle"]
    result = runner.invoke(
        app,
        ["search", str(log_search_image), "--case", str(case_dir), "--term", needle],
    )
    assert result.exit_code == 0, result.output
    assert "search complete" in result.output
    assert "hits:" in result.output


def test_search_help_lists_options() -> None:
    """``search --help`` lists the documented options."""
    result = runner.invoke(app, ["search", "--help"])
    assert result.exit_code == 0
    for option in ("--case", "--term", "--regex", "--ioc", "--hash-set-block"):
        assert option in result.output


def test_version_flag() -> None:
    """``pyautopsy --version`` prints the package version and exits 0."""
    import pyautopsy

    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert pyautopsy.__version__ in result.output


def test_programming_bug_is_not_swallowed_by_the_base_exception_catch(
    tiny_ext4_image: Path, case_dir: Path, monkeypatch
) -> None:
    """A bug still propagates: it is not a ``PyAutopsyError``, so it is not caught.

    Each command catches one base class instead of a hand-listed tuple. That is
    only safe while the base stays narrow — it must cover errors this project
    raises deliberately and nothing else. A ``KeyError`` escaping from the
    orchestrator must reach the caller with its traceback, not be reported as a
    clean operational failure.
    """
    from pyautopsy.cli import main as cli_main

    runner.invoke(app, _ingest_args(tiny_ext4_image, case_dir))

    def boom(*_args: object, **_kwargs: object) -> None:
        raise KeyError("simulated programming bug")

    monkeypatch.setattr(cli_main, "run_walk", boom)

    result = runner.invoke(app, ["walk", str(tiny_ext4_image), "--case", str(case_dir)])
    assert result.exit_code != 0
    assert isinstance(result.exception, KeyError)
    assert "walk failed" not in result.output


def test_shared_image_argument_validates_identically_across_commands(
    case_dir: Path,
) -> None:
    """Every command's IMAGE argument rejects a missing path the same way.

    The argument is declared once and reused, so this pins that the reuse
    actually reaches each command rather than silently dropping the
    ``exists=True`` validation on some of them.
    """
    missing = str(case_dir / "no-such-image.dd")
    for command in ("ingest", "walk", "recover", "logs", "analyze", "search"):
        args = [command, missing, "--case", str(case_dir)]
        if command in ("ingest", "analyze"):
            args += ["--examiner", "X", "--evidence-id", "E1"]
        result = runner.invoke(app, args)
        assert result.exit_code == 2, f"{command}: {result.output}"
        assert "does not exist" in result.output, f"{command}: {result.output}"


@pytest.mark.parametrize("command", ["walk", "recover", "logs", "search"])
def test_missing_case_directory_exits_cleanly_not_with_a_traceback(
    tiny_ext4_image: Path, tmp_path: Path, command: str
) -> None:
    """Pointing a command at a nonexistent case dir is operator error, not a crash.

    Every command that requires a prior ``ingest`` must say so and exit with the
    integrity code. ``logs`` and ``search`` used to dump a raw traceback here:
    they try to record the failure in the case's audit log first, and when the
    case directory does not exist there is nowhere to write it, so the OSError
    from the audit write masked the actionable message.
    """
    missing = tmp_path / "no-such-case"
    result = runner.invoke(app, [command, str(tiny_ext4_image), "--case", str(missing)])
    assert result.exit_code == 1, result.output
    assert "no case database under" in result.output
    assert "run `pyautopsy ingest`" in result.output
