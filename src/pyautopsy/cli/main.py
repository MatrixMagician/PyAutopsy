"""The ``pyautopsy`` Typer CLI (D-12).

Phase 1 ships an ``ingest`` command with the exact D-12 signature plus a
``--version`` flag; Phase 2 adds a ``walk`` command that inventories a
filesystem image into the case store. Each command is a thin shell over its
orchestrator (:func:`pyautopsy.core.ingest.run_ingest` /
:func:`pyautopsy.core.walk.run_walk`): it parses/validates the operator's
arguments (Typer's type-hint-driven validation), invokes the orchestrator, prints
a concise summary, and maps any integrity/operational failure to a non-zero exit
*after* the orchestrator has recorded the FAIL audit event (D-08).

The Typer ``app`` is the ``[project.scripts]`` entry point declared in
``pyproject.toml`` (``pyautopsy = "pyautopsy.cli.main:app"``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import typer

import pyautopsy
from pyautopsy.core.analyze import AnalyzeError, run_analyze
from pyautopsy.core.ingest import IngestError, run_ingest
from pyautopsy.core.walk import WalkError, run_walk
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


@app.command()
def walk(
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
            help="Existing case directory (created by a prior `ingest`).",
        ),
    ],
    timezone: Annotated[
        str,
        typer.Option(
            "--timezone",
            help="IANA zone for FAT local-time handling (default UTC).",
        ),
    ] = "UTC",
    max_hash_size: Annotated[
        int | None,
        typer.Option(
            "--max-hash-size",
            help="Skip hashing files larger than this many bytes (Plan 02-02).",
        ),
    ] = None,
) -> None:
    """Walk a filesystem image into a normalized per-file inventory (META-01).

    Enumerates every volume (D-15), walks each supported filesystem read-only,
    records every entry — including deleted ones (D-18) — as ``files`` rows with
    allocated/unallocated status + inode/MFT address + volume tagging, and records
    any encrypted/unsupported volume as an explicit limitation finding while
    continuing the walk (D-20). Exits non-zero on an operational/integrity failure
    after the orchestrator records a FAIL audit event.
    """
    # (Security V5) Validate the timezone before any work; reject a bad zone with
    # a clear usage error rather than passing an attacker-controlled string on.
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        typer.echo(f"walk failed: invalid --timezone {timezone!r}: {exc}", err=True)
        raise typer.Exit(code=_INTEGRITY_EXIT_CODE) from exc

    try:
        result = run_walk(
            image,
            case,
            timezone=timezone,
            max_hash_size=max_hash_size,
        )
    except (WalkError, ImageOpenError, MountedSourceError, IntegrityError) as exc:
        typer.echo(f"walk failed: {exc}", err=True)
        raise typer.Exit(code=_INTEGRITY_EXIT_CODE) from exc

    typer.echo(
        "walk complete\n"
        f"  case:                 {case}\n"
        f"  files inventoried:    {result.files_inventoried}\n"
        f"  deleted entries:      {result.deleted_count}\n"
        f"  volumes walked:       {result.volumes_walked}\n"
        f"  limitations recorded: {result.limitations_recorded}"
    )


@app.command()
def analyze(
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
            help="Case directory to create (must be a fresh dir, no case.db).",
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
    timezone: Annotated[
        str,
        typer.Option(
            "--timezone",
            help="IANA zone for FAT local-time handling (default UTC).",
        ),
    ] = "UTC",
    max_hash_size: Annotated[
        int | None,
        typer.Option(
            "--max-hash-size",
            help="Skip hashing files larger than this many bytes.",
        ),
    ] = None,
) -> None:
    """Run the full single-command pipeline: ingest → walk → timeline → report.

    Composes the read-only ingest (hashed, audited, end-of-run re-verified), the
    filesystem walk, the MACB timeline, and the report renderers in one process,
    writing ``reports/report.html`` + ``reports/report.json`` (byte-deterministic
    across runs) plus a volatile ``reports/run_metadata.json`` sidecar (W-1). The
    case directory must be fresh — a pre-existing ``case.db`` fails loudly (A2).
    Exits non-zero on any operational/integrity failure after the orchestrator
    records a FAIL audit event (D-08/D-14).
    """
    # (Security V5) Validate the timezone before any work; reject a bad zone with
    # a clear usage error rather than passing an attacker-controlled string on.
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        typer.echo(
            f"analyze failed: invalid --timezone {timezone!r}: {exc}", err=True
        )
        raise typer.Exit(code=_INTEGRITY_EXIT_CODE) from exc

    try:
        result = run_analyze(
            image,
            case,
            examiner=examiner,
            evidence_id=evidence_id,
            acquisition_hash=acquisition_hash,
            timezone=timezone,
            max_hash_size=max_hash_size,
        )
    except (
        AnalyzeError,
        IngestError,
        WalkError,
        ImageOpenError,
        MountedSourceError,
        IntegrityError,
    ) as exc:
        typer.echo(f"analyze failed: {exc}", err=True)
        raise typer.Exit(code=_INTEGRITY_EXIT_CODE) from exc

    typer.echo(
        "analyze complete\n"
        f"  case:               {case}\n"
        f"  files inventoried:  {result.files_inventoried}\n"
        f"  deleted entries:    {result.deleted_count}\n"
        f"  timeline events:    {result.event_count}\n"
        f"  report (json):      {result.report_json_path}\n"
        f"  report (html):      {result.report_html_path}"
    )
