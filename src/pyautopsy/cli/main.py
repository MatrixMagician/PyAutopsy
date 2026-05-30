"""The ``pyautopsy`` Typer CLI (D-12).

Phase 1 ships a single ``ingest`` command with the exact D-12 signature plus a
``--version`` flag. The ``ingest`` command is a thin shell over
:func:`pyautopsy.core.ingest.run_ingest`: it parses/validates the operator's
arguments (Typer's type-hint-driven validation), invokes the orchestrator, prints
a concise success summary, and maps any integrity failure to a non-zero exit
*after* the orchestrator has recorded the FAIL audit event (D-08).

The Typer ``app`` is the ``[project.scripts]`` entry point declared in
``pyproject.toml`` (``pyautopsy = "pyautopsy.cli.main:app"``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

import pyautopsy
from pyautopsy.core.ingest import IngestError, run_ingest
from pyautopsy.evidence.image import ImageOpenError
from pyautopsy.evidence.integrity import IntegrityError, MountedSourceError

app = typer.Typer(
    name="pyautopsy",
    help="Forensically-sound disk-image ingest on The Sleuth Kit.",
    add_completion=False,
    no_args_is_help=True,
)

# Exit code for a loud integrity / read-only-boundary failure (D-08). Distinct
# from Typer's usage-error code (2) so callers can tell a forensic failure from a
# bad invocation.
_INTEGRITY_EXIT_CODE = 1


def _version_callback(value: bool) -> None:
    """Print the package version and exit when ``--version`` is given."""
    if value:
        typer.echo(f"pyautopsy {pyautopsy.__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show the PyAutopsy version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """PyAutopsy — forensically-sound disk-image ingest."""


@app.command()
def ingest(
    image: Annotated[
        Path,
        typer.Argument(
            help="Path to the evidence image (raw/dd file or first E01 segment).",
            exists=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    case: Annotated[
        Path,
        typer.Option(
            "--case",
            help="Case directory to create (case.db, logs/, exports/).",
        ),
    ],
    examiner: Annotated[
        str,
        typer.Option("--examiner", help="Name of the accountable examiner."),
    ],
    evidence_id: Annotated[
        str,
        typer.Option("--evidence-id", help="Examiner-supplied evidence id."),
    ],
    acquisition_hash: Annotated[
        str | None,
        typer.Option(
            "--acquisition-hash",
            help="Optional acquisition hash (md5/sha256 hex) to verify against.",
        ),
    ] = None,
) -> None:
    """Ingest an evidence image read-only into a case (hashed, audited, verified).

    Opens the image read-only, hashes it (MD5+SHA-256), persists the
    chain-of-custody rows, writes the audit log, re-verifies the source hash at
    end of run, and exits 0 — or exits non-zero on any integrity mismatch after
    recording a FAIL audit event (D-08).
    """
    try:
        result = run_ingest(
            image,
            case,
            examiner=examiner,
            evidence_id=evidence_id,
            acquisition_hash=acquisition_hash,
        )
    except (IntegrityError, MountedSourceError, IngestError, ImageOpenError) as exc:
        typer.echo(f"ingest failed: {exc}", err=True)
        raise typer.Exit(code=_INTEGRITY_EXIT_CODE) from exc

    verified = (
        "not supplied"
        if result.acquisition_verified is None
        else "PASS"
        if result.acquisition_verified
        else "FAIL"
    )
    typer.echo(
        "ingest complete\n"
        f"  case:           {case}\n"
        f"  evidence id:    {evidence_id}\n"
        f"  image type:     {result.image_type}\n"
        f"  byte size:      {result.byte_size}\n"
        f"  sha256:         {result.sha256}\n"
        f"  md5:            {result.md5}\n"
        f"  acquisition:    {verified}"
    )
