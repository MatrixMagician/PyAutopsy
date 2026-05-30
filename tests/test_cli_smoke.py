"""End-to-end ``pyautopsy ingest`` smoke test — the Walking Skeleton target.

This test pins the finish line for Phase 1: invoking the exact D-12 CLI
signature must exit 0 and create the case store (``case.db``) and the audit log
(``logs/audit.jsonl``) under the case directory.

It is marked ``xfail(strict=True)`` because the ``ingest`` command is not yet
implemented (the ``pyautopsy.cli.main`` module / Typer app does not exist until
plan 01-04). ``strict=True`` means:

* while ``ingest`` is missing, the test xfails → the suite stays green; and
* the moment plan 01-04 makes it pass, ``strict`` turns the unexpected pass into
  a FAILURE, forcing the executor of 01-04 to remove this xfail marker and let
  the smoke test assert the real contract.

So this single marker both keeps the suite green today and guarantees the
Walking-Skeleton target is wired up (not silently forgotten) tomorrow.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _run_ingest(image: Path, case: Path) -> int:
    """Invoke ``pyautopsy ingest`` against the D-12 signature.

    Returns the process exit code. Raises (e.g. ``ModuleNotFoundError`` /
    ``AttributeError``) while the command does not yet exist — which is exactly
    the expected-failure condition this test documents.
    """
    # Imported lazily so the xfail captures the "not yet implemented" state
    # rather than failing at module import time.
    from pyautopsy.cli.main import app  # noqa: PLC0415 — intentional lazy import
    from typer.testing import CliRunner  # noqa: PLC0415 — intentional lazy import

    result = CliRunner().invoke(
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
    return result.exit_code


@pytest.mark.xfail(
    reason="Walking Skeleton target — ingest command implemented in plan 01-04",
    strict=True,
)
def test_ingest_smoke(tiny_raw_image: Path, case_dir: Path) -> None:
    """`pyautopsy ingest <img> --case <dir> --examiner X --evidence-id E1` works.

    Asserts exit 0 and that the case store + audit log are created. Currently
    xfails because the ``ingest`` command is not implemented (plan 01-04).
    """
    exit_code = _run_ingest(tiny_raw_image, case_dir)

    assert exit_code == 0
    assert (case_dir / "case.db").is_file()
    assert (case_dir / "logs" / "audit.jsonl").is_file()
