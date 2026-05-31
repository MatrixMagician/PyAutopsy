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

import sqlite3
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import typer

import pyautopsy
from pyautopsy.core.analyze import AnalyzeError, run_analyze
from pyautopsy.core.ingest import IngestError, run_ingest
from pyautopsy.core.knownfiles import FilterError, run_filter
from pyautopsy.core.logs import LogsError, run_logs
from pyautopsy.core.recover import RecoverError, run_recover
from pyautopsy.core.search import SearchError, run_search
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


def _hash_sets(
    allow: list[Path] | None, block: list[Path] | None
) -> list[tuple[Path, str]]:
    """Pair each ``--hash-set-allow``/``--hash-set-block`` path with its sense.

    Returns the ``(path, sense)`` list :func:`run_filter` / :func:`run_analyze`
    consume. Order is deterministic (all allow lists in supplied order, then all
    block lists), so two identical invocations filter in the same order (D-41).
    """
    pairs: list[tuple[Path, str]] = []
    for path in allow or []:
        pairs.append((path, "allow"))
    for path in block or []:
        pairs.append((path, "block"))
    return pairs


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
def recover(
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
    max_hash_size: Annotated[
        int | None,
        typer.Option(
            "--max-hash-size",
            help="Skip hashing/writing recovered files larger than this many bytes.",
        ),
    ] = None,
    nsrl: Annotated[
        Path | None,
        typer.Option(
            "--nsrl",
            help="Optional NSRL RDS SQLite DB; runs known-file filtering after "
            "recovery (read-only).",
            exists=True,
            dir_okay=False,
            readable=True,
        ),
    ] = None,
    hash_set_allow: Annotated[
        list[Path] | None,
        typer.Option(
            "--hash-set-allow",
            help="Custom allow-sense hash list (repeatable); runs known-file "
            "filtering after recovery.",
            exists=True,
            dir_okay=False,
            readable=True,
        ),
    ] = None,
    hash_set_block: Annotated[
        list[Path] | None,
        typer.Option(
            "--hash-set-block",
            help="Custom block-sense hash list (repeatable); runs known-file "
            "filtering after recovery.",
            exists=True,
            dir_okay=False,
            readable=True,
        ),
    ] = None,
) -> None:
    """Recover deleted/orphan file content into a confined recovered/ tree.

    Reopens each deleted entry read-only through the native seam, writes its
    surviving bytes under ``<case>/recovered/`` with a deterministic, confined
    name (never the raw deleted name), classifies an honest confidence tier
    (intact vs partial/overwritten — data survival only, never intent), and
    catalogs recovered ``files`` rows (RECOV-01/02/03). Orphans (deleted entries
    whose parent directory is gone) are reported separately. The evidence source
    is never written (D-42). When ``--nsrl``/``--hash-set-*`` are supplied, a
    known-file filtering pass runs after recovery (annotating recovered rows
    too). Exits non-zero on an operational/integrity failure after the
    orchestrator records a FAIL audit event.
    """
    hash_sets = _hash_sets(hash_set_allow, hash_set_block)
    try:
        result = run_recover(image, case, max_hash_size=max_hash_size)
    except (
        RecoverError,
        ImageOpenError,
        MountedSourceError,
        IntegrityError,
    ) as exc:
        typer.echo(f"recover failed: {exc}", err=True)
        raise typer.Exit(code=_INTEGRITY_EXIT_CODE) from exc

    filter_result = None
    if nsrl is not None or hash_sets:
        try:
            filter_result = run_filter(case, nsrl_db=nsrl, hash_sets=hash_sets)
        except (FilterError, OSError, sqlite3.Error) as exc:
            # BL-02: sqlite3.Error is NOT an OSError, so a corrupt examiner-
            # supplied --nsrl DB would otherwise escape this handler and crash
            # with a raw traceback. run_filter lists sqlite3.Error in
            # _EXPECTED_FILTER_ERRORS and re-raises it; map it here to the clean
            # non-zero integrity exit + audit FAIL.
            typer.echo(f"recover filtering failed: {exc}", err=True)
            raise typer.Exit(code=_INTEGRITY_EXIT_CODE) from exc

    summary = (
        "recover complete\n"
        f"  case:                 {case}\n"
        f"  files recovered:      {result.files_recovered}\n"
        f"  intact:               {result.intact_count}\n"
        f"  partial/overwritten:  {result.overwritten_count}\n"
        f"  orphans (separate):   {result.orphan_count}"
    )
    if filter_result is not None:
        summary += (
            f"\n  known matches:        {filter_result.files_matched}"
            f" (nsrl {filter_result.nsrl_matches},"
            f" custom {filter_result.custom_matches})"
        )
    typer.echo(summary)


@app.command()
def logs(
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
) -> None:
    """Parse the image's logs into the shared super-timeline (LOG-01, TIME-02).

    Reads ``auth.log``/``secure`` (incl. rotated ``.1``/``.2.gz`` members,
    reassembled oldest→newest) read-only through the native seam, maps sshd/sudo/
    PAM lines to honest action/outcome events, time-resolves each line to UTC with
    the image's inferred timezone + inferred year FLAGGED per event (never
    asserted as fact), and writes them into the same ``timeline_events`` table as
    filesystem events — so ``get_timeline_events`` returns one merged UTC-ordered
    super-timeline (D-45/D-46/D-47). The evidence source is never written. Exits
    non-zero on an operational/integrity failure after the orchestrator records a
    FAIL audit event.
    """
    try:
        result = run_logs(image, case)
    except (
        LogsError,
        ImageOpenError,
        MountedSourceError,
        IntegrityError,
    ) as exc:
        typer.echo(f"logs failed: {exc}", err=True)
        raise typer.Exit(code=_INTEGRITY_EXIT_CODE) from exc
    except sqlite3.Error as exc:
        # BL-02: sqlite3.Error is NOT an OSError — a corrupt case DB would
        # otherwise escape with a raw traceback. run_logs lists it in
        # _EXPECTED_LOGS_ERRORS and re-raises; map it to the clean integrity exit.
        typer.echo(f"logs failed: {exc}", err=True)
        raise typer.Exit(code=_INTEGRITY_EXIT_CODE) from exc

    summary = (
        "logs complete\n"
        f"  case:           {case}\n"
        f"  log sets:       {result.log_sets}\n"
        f"  events parsed:  {result.events_parsed}\n"
        f"  auth events:    {result.auth_events}"
    )
    typer.echo(summary)


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
    recover: Annotated[
        bool,
        typer.Option(
            "--recover",
            help="Also recover deleted/orphan file content (opt-in; the default "
            "report stays Phase-3 byte-identical).",
        ),
    ] = False,
    nsrl: Annotated[
        Path | None,
        typer.Option(
            "--nsrl",
            help="Optional NSRL RDS SQLite DB; opts into known-file filtering "
            "(read-only).",
            exists=True,
            dir_okay=False,
            readable=True,
        ),
    ] = None,
    hash_set_allow: Annotated[
        list[Path] | None,
        typer.Option(
            "--hash-set-allow",
            help="Custom allow-sense hash list (repeatable); opts into "
            "known-file filtering.",
            exists=True,
            dir_okay=False,
            readable=True,
        ),
    ] = None,
    hash_set_block: Annotated[
        list[Path] | None,
        typer.Option(
            "--hash-set-block",
            help="Custom block-sense hash list (repeatable); opts into "
            "known-file filtering.",
            exists=True,
            dir_okay=False,
            readable=True,
        ),
    ] = None,
    logs: Annotated[
        bool,
        typer.Option(
            "--logs",
            help="Also parse the image's system logs into the super-timeline "
            "(opt-in; the default report stays Phase-4 byte-identical).",
        ),
    ] = False,
    search: Annotated[
        str | None,
        typer.Option(
            "--search",
            help="Literal term to search across allocated/unallocated content + "
            "file hashes; opts into the search-results section (opt-in).",
        ),
    ] = None,
) -> None:
    """Run the full single-command pipeline: ingest → walk → timeline → report.

    Composes the read-only ingest (hashed, audited, end-of-run re-verified), the
    filesystem walk, the MACB timeline, and the report renderers in one process,
    writing ``reports/report.html`` + ``reports/report.json`` (byte-deterministic
    across runs) plus a volatile ``reports/run_metadata.json`` sidecar (W-1). The
    case directory must be fresh — a pre-existing ``case.db`` fails loudly (A2).
    Deleted-file recovery (``--recover``) and known-file filtering
    (``--nsrl``/``--hash-set-*``) are OPT-IN (D-40): without them the report is
    byte-identical to the Phase-3 baseline. Exits non-zero on any
    operational/integrity failure after the orchestrator records a FAIL audit
    event (D-08/D-14).
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

    hash_sets = _hash_sets(hash_set_allow, hash_set_block)
    try:
        result = run_analyze(
            image,
            case,
            examiner=examiner,
            evidence_id=evidence_id,
            acquisition_hash=acquisition_hash,
            timezone=timezone,
            max_hash_size=max_hash_size,
            recover=recover,
            nsrl_db=nsrl,
            hash_sets=hash_sets,
            logs=logs,
            search=search,
        )
    except (
        AnalyzeError,
        IngestError,
        WalkError,
        RecoverError,
        FilterError,
        LogsError,
        SearchError,
        ImageOpenError,
        MountedSourceError,
        IntegrityError,
        # BL-02: sqlite3.Error is not an OSError; run_analyze lists it in
        # _EXPECTED_ANALYZE_ERRORS and re-raises a corrupt --nsrl DB failure, so
        # map it to the clean integrity exit instead of crashing with a traceback.
        sqlite3.Error,
    ) as exc:
        typer.echo(f"analyze failed: {exc}", err=True)
        raise typer.Exit(code=_INTEGRITY_EXIT_CODE) from exc

    typer.echo(
        "analyze complete\n"
        f"  case:               {case}\n"
        f"  files inventoried:  {result.files_inventoried}\n"
        f"  deleted entries:    {result.deleted_count}\n"
        f"  files recovered:    {result.files_recovered}\n"
        f"  known matches:      {result.known_matches}\n"
        f"  log events:         {result.log_events}\n"
        f"  search hits:        {result.search_hits}\n"
        f"  timeline events:    {result.event_count}\n"
        f"  report (json):      {result.report_json_path}\n"
        f"  report (html):      {result.report_html_path}"
    )


@app.command()
def search(
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
    term: Annotated[
        list[str] | None,
        typer.Option(
            "--term",
            help="Literal (or, with --regex, regex) needle to search for "
            "(repeatable).",
        ),
    ] = None,
    regex: Annotated[
        bool,
        typer.Option(
            "--regex",
            help="Treat each --term as a regular expression (ReDoS-bounded).",
        ),
    ] = False,
    ioc: Annotated[
        Path | None,
        typer.Option(
            "--ioc",
            help="IOC list file; its indicators are searched as literal terms.",
            exists=True,
            dir_okay=False,
            readable=True,
        ),
    ] = None,
    hash_set_block: Annotated[
        list[Path] | None,
        typer.Option(
            "--hash-set-block",
            help="Known-bad hash list (repeatable); matched against the "
            "inventory's file hashes.",
            exists=True,
            dir_okay=False,
            readable=True,
        ),
    ] = None,
) -> None:
    """Search allocated content, unallocated space, and file hashes (SEARCH-01/02).

    Streams each ``--term`` (literal, or regex with ``--regex``) and any ``--ioc``
    indicators over every volume's allocated file content and unallocated space,
    reporting hits by file + absolute byte offset (boundary-spanning matches
    handled). Known-bad hash lists (``--hash-set-block``) are matched against the
    inventory's file hashes (reusing the Phase-4 matcher). All hits persist as
    ``search_hits`` rows in a deterministic order. The evidence source is read
    read-only and never mounted (D-42). Exits non-zero on an operational/integrity
    failure after the orchestrator records a FAIL audit event.
    """
    terms = [t.encode("utf-8") for t in (term or [])]
    literal_terms: list[bytes] = [] if regex else terms
    regex_terms: list[bytes] = terms if regex else []

    # Read known-bad hash lists as data (tolerant parser handles each file).
    bad_hashes: list[str] = []
    for path in hash_set_block or []:
        try:
            bad_hashes.extend(path.read_text(encoding="utf-8").splitlines())
        except UnicodeDecodeError as exc:
            typer.echo(
                f"search failed: hash list {path} is not valid UTF-8: {exc}",
                err=True,
            )
            raise typer.Exit(code=_INTEGRITY_EXIT_CODE) from exc

    try:
        result = run_search(
            image,
            case,
            terms=literal_terms,
            regexes=regex_terms,
            ioc_file=ioc,
            bad_hashes=bad_hashes,
        )
    except (
        SearchError,
        ImageOpenError,
        MountedSourceError,
        IntegrityError,
        # BL-02: sqlite3.Error is NOT an OSError; run_search lists it in
        # _EXPECTED_SEARCH_ERRORS and re-raises a corrupt case DB failure, so map
        # it to the clean integrity exit instead of crashing with a traceback.
        sqlite3.Error,
    ) as exc:
        typer.echo(f"search failed: {exc}", err=True)
        raise typer.Exit(code=_INTEGRITY_EXIT_CODE) from exc

    typer.echo(
        "search complete\n"
        f"  case:               {case}\n"
        f"  hits:               {result.hits}\n"
        f"  unallocated hits:   {result.unallocated_hits}\n"
        f"  known-bad hits:     {result.hash_hits}"
    )
