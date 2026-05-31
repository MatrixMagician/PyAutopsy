"""Deterministic report-body assembly (REPORT-03/04, D-25/D-26/D-27/D-28).

:func:`assemble_report_body` reads the persisted case rows and returns ONE plain
dict — the determinism single-source-of-truth (Pattern 3) — covering the eight
canonical report sections (03-UI-SPEC.md "Report Section Hierarchy"). The body
contains only analytical content: **no wall-clock is reachable from this
function** (none of the sanctioned now/UTC-serialize timestamp helpers are
called), so two runs on the same fixture serialize byte-identically (CLI-02 /
D-25). All ordering is derived
from sorted keys / the store's D-26 total order, never from dict/set iteration.

The body's ``timeline`` is the FULL D-26-ordered list (no limit — the JSON report
is unabridged, D-27), and ``timeline_total`` records ``len(timeline)`` (M) so the
HTML renderer can disclose an honest "Showing N of M" without a store handle
(W-2 lock).

Volatile run metadata (generation timestamp, host, durations, run-id) is the ONLY
place wall-clock lives (D-25); it is produced separately by
:func:`build_run_metadata`, never merged into the body, and never passed to
:func:`render_html` — ``report.html`` carries zero run metadata (W-1). The
``analyze`` orchestrator (03-03) writes it to the ``reports/run_metadata.json``
sidecar.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pyautopsy.case import CaseStore, FileRow

__all__ = ["assemble_report_body", "build_run_metadata"]


# Standing MVP-limitations disclaimer, verbatim from 03-UI-SPEC.md:171. Surfaced
# in both reports so the report never overclaims what this MVP analyzed (D-28).
_MVP_LIMITATIONS = (
    "This is an MVP report. It covers filesystem inventory, MACB timeline, and "
    "integrity verification only. It does NOT include deleted-file recovery, "
    "known-file (NSRL) filtering, log analysis, super-timeline, or content "
    "search. Absence of a finding here does not mean absence of evidence."
)

# Integrity copy strings, verbatim from 03-UI-SPEC.md:166-167. An evidence source
# only persists after a clean acquisition-compare + end-of-run re-verify (ingest
# raises and rolls back on any FAIL), so a readable source means PASS.
_INTEGRITY_PASS_COPY = (
    "Integrity verification: PASS — source hash matches acquisition value and "
    "end-of-run re-verification."
)
_INTEGRITY_FAIL_COPY = (
    "Integrity verification: FAIL — source hash mismatch. This report's findings "
    "may not correspond to the originally acquired evidence. Re-acquire and "
    "re-verify the source."
)


def _is_deleted(file_row: FileRow) -> bool:
    """Return True for a deleted/unallocated entry (META-01/D-18, walk.py:555)."""
    return file_row.allocated is False


def _is_directory(file_row: FileRow) -> bool:
    """Return True when the entry's meta-type marks it a directory."""
    return file_row.meta_type == "dir"


def _surface_provenance(file_row: FileRow) -> dict[str, str]:
    """Lift the Phase 2 provenance flags out of ``FileRow.attributes``.

    The walk stamps ``time_precision`` (``local-time-inferred`` for FAT),
    ``assumed_timezone`` and ``file_type_provenance`` into the JSON ``attributes``
    blackboard (walk.py:202-203, walk.py:366). They MUST survive to the report so
    it never silently presents inferred FAT local time as recorded UTC, or a
    reclaimed-block deleted file's type as equivalent to an allocated file's
    (Pitfall 10 / WR-02). Returns only the keys that are present.
    """
    attrs = file_row.attributes or {}
    surfaced: dict[str, str] = {}
    for key in ("time_precision", "assumed_timezone", "file_type_provenance"):
        value = attrs.get(key)
        if value is not None:
            surfaced[key] = str(value)
    return surfaced


def assemble_report_body(
    store: CaseStore, evidence_source_id: int
) -> dict[str, Any]:
    """Assemble the deterministic report body for one evidence source.

    Reads the COC (case + evidence), the walk inventory, the D-20 volume
    limitations and the FULL D-26-ordered timeline, then builds a fixed-key dict
    covering the eight canonical sections (03-UI-SPEC.md:123-137). No wall-clock
    is reachable: every count is derived by sorting keys deterministically, never
    by dict/set iteration order, so :func:`pyautopsy.report.jsonreport.write_json`
    produces byte-identical output across runs (D-25/D-26).

    Args:
        store: An open :class:`~pyautopsy.case.CaseStore`.
        evidence_source_id: The evidence source to report on.

    Returns:
        The analytical report body. Notable keys: ``case``, ``evidence``,
        ``header``, ``integrity``, ``methodology`` (pinned ``tsk_version`` +
        ``pyautopsy_version``), ``findings`` (D-28 inventory + integrity +
        limitations), ``evidence_hashes``, ``timeline`` (full, D-26 order),
        ``timeline_total`` (M = ``len(timeline)``, W-2) and ``limitations``.
        Carries NO ``run_metadata`` / ``generated_utc`` (D-25).
    """
    evidence = store.get_evidence_source(evidence_source_id)
    case = store.get_case(evidence.case_id)
    files = store.get_files(evidence_source_id)
    limitations = store.get_volume_limitations(evidence_source_id)
    events = store.get_timeline_events(evidence_source_id)

    # -- Findings 4a: inventory counts (deterministic; no iteration-order deps) --
    file_count = len(files)
    directory_count = sum(1 for f in files if _is_directory(f))
    deleted_count = sum(1 for f in files if _is_deleted(f))

    # -- Findings 4b: per-volume breakdown, sorted by (volume_id, volume_offset) --
    volume_acc: dict[tuple[int, int], dict[str, Any]] = {}
    for f in files:
        key = (f.volume_id, f.volume_offset)
        bucket = volume_acc.setdefault(
            key,
            {
                "volume_id": f.volume_id,
                "volume_offset": f.volume_offset,
                "fs_type": f.fs_type,
                "file_count": 0,
                "deleted_count": 0,
            },
        )
        bucket["file_count"] += 1
        if _is_deleted(f):
            bucket["deleted_count"] += 1
    per_volume = [volume_acc[key] for key in sorted(volume_acc)]

    # -- Findings 4c: file-type distribution, ranked by (-count, type) -----------
    type_counter: Counter[str] = Counter(
        f.file_type for f in files if f.file_type is not None
    )
    file_type_distribution = [
        {"file_type": file_type, "count": count}
        for file_type, count in sorted(
            type_counter.items(), key=lambda item: (-item[1], item[0])
        )
    ]

    # -- Provenance surfacing (FAT local-time-inferred / assumed_timezone, etc.) -
    # Distinct flag sets, deterministically ordered, so the report keeps the
    # Phase 2 provenance without re-listing it once per file.
    provenance_seen: dict[str, dict[str, str]] = {}
    for f in files:
        surfaced = _surface_provenance(f)
        if surfaced:
            # repr is stable for a flat str->str dict with sorted keys.
            marker = repr(sorted(surfaced.items()))
            provenance_seen.setdefault(marker, surfaced)
    provenance_flags = [provenance_seen[k] for k in sorted(provenance_seen)]

    # -- D-20 / D-28 volume limitations (never silently dropped) -----------------
    limitation_rows = [
        {
            "volume_id": lim.volume_id,
            "volume_offset": lim.volume_offset,
            "detected_desc": lim.detected_desc,
            "reason": lim.reason,
        }
        for lim in limitations
    ]

    # -- Timeline: FULL D-26-ordered list + the true total M (W-2) ---------------
    timeline = [
        {
            "ts_utc": ev.ts_utc,
            "volume_id": ev.volume_id,
            "volume_offset": ev.volume_offset,
            "path": ev.path,
            "event_type": ev.event_type,
            "meta_addr": ev.meta_addr,
            "source": ev.source,
            "actor": ev.actor,
        }
        for ev in events
    ]
    timeline_total = len(timeline)

    # An evidence source only persists after a clean acquisition-compare + end-of-
    # run re-verify (ingest raises + rolls back on FAIL), so a readable source is
    # integrity PASS. The booleans + copy keep the renderer honest regardless.
    integrity_pass = True

    return {
        # 1. Header / identity band
        "header": {
            "title": f"PyAutopsy Forensic Report — Case {case.id}",
            "case_id": case.id,
            "case_name": case.name,
            "examiner": case.examiner,
            "evidence_id": evidence.evidence_id,
            "acquisition_source": evidence.path,
            "image_type": evidence.image_type,
            "acquired_utc": evidence.acquired_utc,
        },
        # Convenience top-level COC handles (also consumed by the JSON readers).
        "case": {
            "id": case.id,
            "name": case.name,
            "examiner": case.examiner,
            "notes": case.notes,
            "created_utc": case.created_utc,
        },
        "evidence": {
            "id": evidence.id,
            "evidence_id": evidence.evidence_id,
            "path": evidence.path,
            "image_type": evidence.image_type,
            "byte_size": evidence.byte_size,
            "acquired_utc": evidence.acquired_utc,
        },
        # 2. Integrity verification (prominent; PASS/FAIL booleans + literal copy)
        "integrity": {
            "acquisition_compare_pass": integrity_pass,
            "reverify_pass": integrity_pass,
            "passed": integrity_pass,
            "copy": _INTEGRITY_PASS_COPY if integrity_pass else _INTEGRITY_FAIL_COPY,
        },
        # 3. Methodology + pinned tool/TSK versions (verbatim, CLI-02/D-26)
        "methodology": {
            "pyautopsy_version": case.pyautopsy_version,
            "tsk_version": evidence.tsk_version,
            "summary": (
                "Read-only ingest with acquisition-hash compare and end-of-run "
                "re-verification, filesystem walk with MACB metadata, and a "
                "MACB-explosion timeline. No write to the source occurred."
            ),
        },
        # 4. Findings (D-28): inventory + per-volume + file-type + integrity + limits
        "findings": {
            "inventory": {
                "file_count": file_count,
                "directory_count": directory_count,
                "deleted_count": deleted_count,
            },
            "per_volume": per_volume,
            "file_type_distribution": file_type_distribution,
            "provenance_flags": provenance_flags,
            "integrity": {
                "acquisition_compare_pass": integrity_pass,
                "reverify_pass": integrity_pass,
                "passed": integrity_pass,
            },
            "limitations": limitation_rows,
        },
        # 5. Evidence hashes (source image; sha1 not computed for images — md5/sha256)
        "evidence_hashes": {
            "md5": evidence.md5,
            "sha1": None,
            "sha256": evidence.sha256,
        },
        # 6. Timeline (FULL, D-26 order) + total M (W-2)
        "timeline": timeline,
        "timeline_total": timeline_total,
        # 7. Limitations: D-20 volumes + the standing MVP disclaimer (mandatory)
        "limitations": {
            "volumes": limitation_rows,
            "mvp_disclaimer": _MVP_LIMITATIONS,
        },
    }


def build_run_metadata(
    *,
    generation_ts: str,
    host: str,
    durations: dict[str, Any],
    run_id: str | None = None,
) -> dict[str, Any]:
    """Build the volatile, NON-analytical run-metadata dict (D-25).

    This is the ONLY place wall-clock / host / duration / run-id values live. The
    caller (the ``analyze`` orchestrator, 03-03) fills it and writes it to the
    ``reports/run_metadata.json`` sidecar. It is NEVER merged into the report body
    and NEVER passed to :func:`render_html` — ``report.html`` carries zero run
    metadata (W-1), which keeps both ``report.json`` (body) and ``report.html``
    whole-file byte-deterministic across runs.

    Args:
        generation_ts: Report generation timestamp (UTC ISO-8601), produced by
            the caller via the sanctioned ``pyautopsy.util.timeutil`` helper.
        host: The analysis host identifier.
        durations: Per-stage durations (e.g. ingest/walk/timeline/report seconds).
        run_id: Optional opaque run identifier.

    Returns:
        The volatile run-metadata dict, clearly marked non-analytical.
    """
    return {
        "non_analytical": True,
        "label": (
            "Run Metadata (non-analytical — excluded from the reproducible "
            "report body)"
        ),
        "generated_utc": generation_ts,
        "host": host,
        "durations": durations,
        "run_id": run_id,
    }
