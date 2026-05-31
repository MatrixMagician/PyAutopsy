"""Single-command ``analyze`` orchestrator — the end-to-end MVP slice (CLI-01).

:func:`run_analyze` composes the proven Phase 1/2 orchestrators
(:func:`pyautopsy.core.ingest.run_ingest` then
:func:`pyautopsy.core.walk.run_walk`) and the Phase 3 producers
(:func:`pyautopsy.timeline.builder.build_timeline` +
:func:`pyautopsy.report` assembly/render) into ONE in-process pipeline:
image → ingest (read-only, hashed, audited, end-of-run re-verified) → walk
(per-file inventory) → timeline (MACB explosion) → report set (report.json +
report.html). The Phase 1 end-of-run re-verify still runs because it lives
inside :func:`run_ingest` (ingest.py:246-247) — this module never re-implements
it.

Like :mod:`pyautopsy.core.walk` and :mod:`pyautopsy.timeline.builder`, this is an
orchestration-tier module that **imports no native bindings** (no ``pytsk3`` /
``pyewf``): it drives the lower tiers through the existing orchestrators (D-14,
threat T-03-03).

Two determinism guarantees are load-bearing here (CLI-02 / W-1):

* **fresh-case (A2)**: ``run_analyze`` fails loudly with :class:`AnalyzeError`
  if ``case_dir/case.db`` already exists, BEFORE doing any work — so an
  ``analyze`` run can never append to / confuse an existing case (threat
  T-03-12).
* **run metadata segregation (W-1)**: the volatile run-metadata dict (the ONLY
  wall-clock site, D-25) is written to a ``reports/run_metadata.json`` SIDECAR
  only — it is never merged into the body and never passed to
  :func:`render_html`. ``report.json`` (body) and ``report.html`` are therefore
  whole-file byte-deterministic across runs; ``run_metadata.json`` is the single
  volatile file.

The orchestrator records ``analyze.start`` / ``analyze.end`` self-audit events
(REPORT-02, threat T-03-13) like ingest/walk, writes a terminal FAIL event
before re-raising an expected forensic failure (mapped by the CLI to the
integrity exit code, threat T-03-14), and records a DISTINCT ``analyze.crashed``
event for a genuine programming bug.
"""

from __future__ import annotations

import json
import socket
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pyautopsy.audit import AuditLog
from pyautopsy.case import CaseStore
from pyautopsy.core.ingest import IngestError, run_ingest
from pyautopsy.core.knownfiles import FilterError, run_filter
from pyautopsy.core.recover import RecoverError, run_recover
from pyautopsy.core.walk import WalkError, run_walk
from pyautopsy.evidence import integrity
from pyautopsy.evidence.image import ImageOpenError
from pyautopsy.report import (
    assemble_report_body,
    build_run_metadata,
    render_html,
    write_json,
)
from pyautopsy.report.jsonreport import _confined_reports_dir
from pyautopsy.timeline.builder import build_timeline
from pyautopsy.util.timeutil import iso_utc, utc_now

__all__ = ["AnalyzeError", "AnalyzeResult", "run_analyze"]


class AnalyzeError(Exception):
    """Raised when the pipeline cannot proceed for a non-integrity reason.

    Chiefly: ``case_dir/case.db`` already exists, which would make ``analyze``
    append to / confuse an existing case and break the reproducibility guarantee
    (fresh-case semantics, A2 / threat T-03-12). Integrity / read-only-boundary
    failures still surface as
    :class:`~pyautopsy.evidence.integrity.MountedSourceError` /
    :class:`~pyautopsy.evidence.integrity.IntegrityError` (raised by the composed
    orchestrators), and ingest/walk input-validation failures surface as
    :class:`~pyautopsy.core.ingest.IngestError` /
    :class:`~pyautopsy.core.walk.WalkError`.
    """


# (Mirrors walk's _EXPECTED_WALK_ERRORS, walk.py:225-233.) The operational
# exception set the analyze pipeline legitimately expects: our own AnalyzeError,
# an integrity / read-only-boundary failure, an unopenable image, an FS/case-store
# error, or the composed orchestrators' own errors. These are recorded as an
# ``analyze.error`` FAIL and re-raised (traceback preserved). Anything OUTSIDE this
# set is a genuine programming bug, recorded under a DISTINCT ``analyze.crashed``
# event so the audit trail never conflates a bug with an expected operational
# failure.
_EXPECTED_ANALYZE_ERRORS: tuple[type[BaseException], ...] = (
    AnalyzeError,
    IngestError,
    WalkError,
    RecoverError,
    FilterError,
    integrity.MountedSourceError,
    integrity.IntegrityError,
    ImageOpenError,
    OSError,
    sqlite3.Error,
)


@dataclass(frozen=True, slots=True)
class AnalyzeResult:
    """The analytical outcome of a successful ``analyze`` run.

    Carries only analytical (reproducible) content — never wall-clock metadata —
    so the CLI can print a deterministic summary and the reproducibility test can
    compare two runs (PITFALLS P3). The volatile run metadata (generation
    timestamp, host, durations) lives ONLY in the ``run_metadata.json`` sidecar,
    never here (D-25 / W-1).

    Attributes:
        case_id: Surrogate id of the persisted ``cases`` row.
        evidence_source_id: Surrogate id of the persisted ``evidence_sources``
            row.
        files_inventoried: Total ``files`` rows written by the walk.
        deleted_count: How many of those were deleted/unallocated (D-18).
        event_count: How many ``timeline_events`` rows the MACB explosion wrote.
        files_recovered: How many deleted/orphan entries recovery wrote (0 when
            recovery was not requested — D-40 opt-in).
        known_matches: How many neutral known-file annotations filtering wrote
            (0 when no ``--nsrl``/``--hash-set`` input was supplied — D-40 opt-in).
        report_json_path: Path of the written ``reports/report.json``.
        report_html_path: Path of the written ``reports/report.html``.
    """

    case_id: int
    evidence_source_id: int
    files_inventoried: int
    deleted_count: int
    event_count: int
    files_recovered: int
    known_matches: int
    report_json_path: Path
    report_html_path: Path


_REPORTS_SUBDIR = "reports"
_RUN_METADATA_NAME = "run_metadata.json"


def _write_run_metadata(case_dir: Path, run_metadata: dict[str, object]) -> Path:
    """Write volatile run metadata to the ``reports/run_metadata.json`` sidecar.

    Reuses the json-report determinism idiom (``sort_keys`` + ``ensure_ascii``,
    jsonreport.py:76) and routes the path through the SAME ``_confined_reports_dir``
    guard the two report writers use (WR-01), so all three forensic outputs
    (report.json, report.html, run_metadata.json) share identical case-dir
    confinement — a symlinked/relative ``case_dir`` cannot redirect the sidecar
    outside the case while leaving the reports confined (threat T-03-07). This
    sidecar is the single volatile file (W-1) — it is NEVER merged into the body
    or passed to ``render_html``.
    """
    reports_dir = _confined_reports_dir(case_dir)
    path = reports_dir / _RUN_METADATA_NAME
    serialized = json.dumps(run_metadata, sort_keys=True, ensure_ascii=False)
    path.write_text(serialized, encoding="utf-8")
    return path


def run_analyze(
    image: str | Path,
    case_dir: str | Path,
    *,
    examiner: str,
    evidence_id: str,
    acquisition_hash: str | None = None,
    timezone: str = "UTC",
    max_hash_size: int | None = None,
    recover: bool = False,
    nsrl_db: str | Path | None = None,
    hash_sets: Sequence[tuple[str | Path, str]] = (),
) -> AnalyzeResult:
    """Run the full single-command pipeline: ingest → walk → timeline → report (CLI-01).

    Composes the existing :func:`run_ingest` and :func:`run_walk` orchestrators
    (the Phase 1 end-of-run re-verify runs inside :func:`run_ingest`), then builds
    the MACB timeline and renders the report set — all in one process. Fails
    loudly with :class:`AnalyzeError` if a ``case.db`` already exists under
    ``case_dir`` (fresh-case semantics, A2). The volatile run metadata is written
    ONLY to the ``reports/run_metadata.json`` sidecar (D-25 / W-1), so
    ``report.json`` and ``report.html`` stay whole-file byte-deterministic across
    runs (CLI-02).

    Args:
        image: Path to the evidence image (raw/dd file or first E01 segment).
        case_dir: Target case directory; must NOT already contain a ``case.db``.
        examiner: Name of the accountable examiner (forwarded to ingest).
        evidence_id: Examiner-supplied evidence id (forwarded to ingest).
        acquisition_hash: Optional acquisition hash (md5/sha256 hex) to verify
            against on ingest (D-08).
        timezone: IANA zone for FAT local-time handling in the walk (validated by
            the caller; default UTC).
        max_hash_size: Skip hashing files larger than this many bytes (walk knob).
        recover: When ``True``, run deleted/orphan-file recovery
            (:func:`pyautopsy.core.recover.run_recover`) after the walk so the
            report gains its recovered/orphan sections (D-40 opt-in). When
            ``False`` (default) recovery is skipped and the report stays
            byte-identical to the Phase-3 baseline.
        nsrl_db: Optional path to an examiner-supplied NSRL RDS SQLite DB. When
            supplied (or ``hash_sets`` is non-empty), the known-file filtering
            pass (:func:`pyautopsy.core.knownfiles.run_filter`) runs after the
            walk/recovery (D-40 opt-in); otherwise filtering is skipped entirely.
        hash_sets: ``(path, sense)`` pairs for custom allow/block hash lists.
            Supplying any of these (or ``nsrl_db``) opts the pipeline into the
            filtering pass.

    Returns:
        An :class:`AnalyzeResult` with the analytical pipeline outcome (no
        wall-clock).

    Raises:
        AnalyzeError: If ``case_dir/case.db`` already exists (fresh-case, A2).
        IngestError / WalkError: From the composed orchestrators.
        MountedSourceError / ImageOpenError / IntegrityError: From the composed
            orchestrators (read-only-boundary / open / integrity failures).
    """
    image_path = Path(image).resolve()
    case_path = Path(case_dir).resolve()

    # (A2) Fresh-case semantics — refuse to run into an existing case BEFORE any
    # work, so analyze can never append to / confuse a prior case and break the
    # reproducibility guarantee (threat T-03-12). The audit log is bound only
    # after this guard (the case dir / logs/ may not exist yet).
    if (case_path / "case.db").exists():
        raise AnalyzeError(
            f"a case already exists at {case_path / 'case.db'}; `analyze` requires "
            "a fresh case directory (A2) — point --case at a new directory so the "
            "report set is reproducible and the prior case is never confused"
        )

    # (1) Ingest (read-only, hashed, audited, end-of-run RE-VERIFY runs INSIDE
    #     run_ingest at ingest.py:246-247 — never re-implemented here). This also
    #     creates the case store + logs/ layout the audit log below relies on.
    ingest_result = run_ingest(
        image_path,
        case_path,
        examiner=examiner,
        evidence_id=evidence_id,
        acquisition_hash=acquisition_hash,
    )

    # The case dir + logs/ now exist (created by ingest); bind the self-audit.
    audit = AuditLog(case_path)
    # (D-40) Filtering runs only when the examiner supplied a reference set —
    # an NSRL DB or at least one custom hash list. Recovery runs only when
    # explicitly requested. With NEITHER, the pipeline is byte-identical to the
    # Phase-3 baseline (test_default_analyze_unchanged).
    filter_requested = nsrl_db is not None or len(tuple(hash_sets)) > 0
    audit.write(
        "analyze.start",
        image=str(image_path),
        case_dir=str(case_path),
        examiner=examiner,
        evidence_id=evidence_id,
        timezone=timezone,
        max_hash_size=max_hash_size,
        recover=recover,
        filter=filter_requested,
    )

    store: CaseStore | None = None
    files_recovered = 0
    known_matches = 0
    try:
        # (2) Walk the filesystem into the per-file inventory (META-01).
        walk_result = run_walk(
            image_path,
            case_path,
            timezone=timezone,
            max_hash_size=max_hash_size,
        )
        source_id = ingest_result.evidence_source_id

        # (2a) OPT-IN recovery (D-40): recover deleted/orphan content ONLY when
        # requested. Runs BEFORE filtering so the filter pass can also annotate
        # recovered rows (knownfiles reads allocated + recovered alike). Never
        # writes the source (D-42) — run_recover re-asserts the not-mounted guard.
        if recover:
            recover_result = run_recover(
                image_path,
                case_path,
                evidence_source_id=source_id,
                max_hash_size=max_hash_size,
            )
            files_recovered = recover_result.files_recovered

        # (2b) OPT-IN known-file filtering (D-40): only when an NSRL DB or a
        # custom hash list was supplied. The store owns match ordering (D-41).
        if filter_requested:
            filter_result = run_filter(
                case_path,
                nsrl_db=nsrl_db,
                hash_sets=hash_sets,
                evidence_source_id=source_id,
            )
            known_matches = filter_result.nsrl_matches + filter_result.custom_matches

        # (3) Build the timeline + assemble/render the report set, reading back
        #     through one open store.
        store = CaseStore.open(case_path)
        event_count = build_timeline(store, source_id)
        # (WR-02) Pass the REAL acquisition-compare outcome through so the report
        # renders an honest integrity state (verified-pass / not-compared / fail)
        # instead of a hardcoded PASS: None = no acquisition hash supplied,
        # True = supplied and matched (a FAIL would have raised in ingest).
        # (D-40 honesty) Tell the body what ACTUALLY ran so the MVP-limitations
        # disclaimer neither denies a capability that ran nor claims one that
        # did not. With both False the body is byte-identical to the Phase-3
        # baseline (test_default_analyze_unchanged).
        body = assemble_report_body(
            store,
            source_id,
            acquisition_verified=ingest_result.acquisition_verified,
            recovery_ran=recover,
            filtering_ran=filter_requested,
        )
        json_path = write_json(body, case_path)
        # (W-1) render_html takes NO run_metadata argument — report.html carries
        # zero run metadata, so it stays byte-deterministic across runs.
        render_html(body, case_path)
        html_path = (case_path / _REPORTS_SUBDIR / "report.html").resolve()

        # (D-25 / W-1) The ONLY wall-clock site: the volatile run metadata is
        # assembled separately and written to the run_metadata.json SIDECAR. It
        # never touches the body or report.html.
        run_metadata = build_run_metadata(
            generation_ts=iso_utc(utc_now()),
            host=socket.gethostname(),
            durations={},
        )
        _write_run_metadata(case_path, run_metadata)

        audit.write(
            "analyze.end",
            outcome="SUCCESS",
            case_id=ingest_result.case_id,
            evidence_source_id=source_id,
            files_inventoried=walk_result.files_inventoried,
            deleted_count=walk_result.deleted_count,
            event_count=event_count,
            files_recovered=files_recovered,
            known_matches=known_matches,
        )
    except _EXPECTED_ANALYZE_ERRORS as exc:
        # An EXPECTED operational failure: leave a terminal FAIL event before
        # propagating (the CLI maps it to the integrity exit code), then re-raise
        # with the traceback preserved (threat T-03-14).
        audit.write(
            "analyze.error",
            outcome="FAIL",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise
    except Exception as exc:
        # An UNEXPECTED error — a genuine programming bug, not an operational
        # failure. Record it under a DISTINCT ``analyze.crashed`` event so the
        # audit trail never conflates a bug with an expected failure, then
        # re-raise unwrapped so the bug surfaces with its full traceback.
        audit.write(
            "analyze.crashed",
            outcome="FAIL",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise
    finally:
        if store is not None:
            store.close()

    return AnalyzeResult(
        case_id=ingest_result.case_id,
        evidence_source_id=source_id,
        files_inventoried=walk_result.files_inventoried,
        deleted_count=walk_result.deleted_count,
        event_count=event_count,
        files_recovered=files_recovered,
        known_matches=known_matches,
        report_json_path=json_path,
        report_html_path=html_path,
    )
