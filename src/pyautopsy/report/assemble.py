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

# ``Stage`` is used at runtime (coverage is read from the case store), unlike the
# type-only imports below.
from pyautopsy.case import Stage

if TYPE_CHECKING:
    from pyautopsy.case import CaseStore, FileRow

__all__ = ["assemble_report_body", "build_run_metadata"]


# Neutral intro for the Known-File Filtering section (FILTER-01, D-38). This is
# NOISE REDUCTION, not classification: a "known" file is one whose hash appears
# in a reference set (NSRL or a custom list) — the report makes NO claim that a
# known file is good/safe or that an unknown file is bad/suspicious.
_KNOWN_FILTER_INTRO = (
    "Known-File Filtering matches each file's hash against reference sets (the "
    "NSRL Reference Data Set and any supplied custom hash lists) purely to "
    "reduce review noise. A match means the hash is KNOWN to that set — it is "
    "not a judgement of the file's content: a known file is not asserted to be "
    "good or safe, and an unknown file is not asserted to be bad or suspicious. "
    "Allow/block is recorded only as the supplied list's sense, not as a verdict."
)

# Standing MVP-limitations disclaimer, verbatim from 03-UI-SPEC.md:171. This is
# the DEFAULT-PATH text: it is rendered VERBATIM whenever neither deleted-file
# recovery nor known-file filtering ran, so a plain ``analyze`` report stays
# byte-identical to the Phase-3 baseline (D-40 / test_default_analyze_unchanged).
# When recovery and/or filtering DID run, :func:`_mvp_limitations` rebuilds this
# copy honestly so it never denies a capability that ran (D-28/D-32 — neither
# over- nor under-claim what the report actually covers).
_MVP_LIMITATIONS = (
    "This is an MVP report. It covers filesystem inventory, MACB timeline, and "
    "integrity verification only. It does NOT include deleted-file recovery, "
    "known-file (NSRL) filtering, log analysis, super-timeline, or content "
    "search. Absence of a finding here does not mean absence of evidence."
)


def _mvp_limitations(
    *,
    recovery_ran: bool,
    filtering_ran: bool,
    logs_ran: bool = False,
    search_ran: bool = False,
) -> str:
    """Return the honest MVP-limitations disclaimer for what ACTUALLY ran.

    When NONE of recovery/filtering/logs/search ran, returns
    :data:`_MVP_LIMITATIONS` verbatim — so the default-path report stays
    byte-identical to the Phase-3/4 baseline (D-40/D-48). When any of them ran,
    the disclaimer is rebuilt so it (a) no longer flatly asserts the report
    EXCLUDES the feature that ran, and (b) carries that feature's honest caveat —
    recovery is best-effort data survival with carving deferred (CARVE-01);
    NSRL/custom filtering is examiner-supplied noise reduction, not an
    adjudication of any file; log analysis carries inferred time/order as a flag,
    never as fact (D-46); content search reports located evidence, not a verdict
    (D-28/D-32 — no over/under-claim, no good/bad language).
    """
    if not recovery_ran and not filtering_ran and not logs_ran and not search_ran:
        return _MVP_LIMITATIONS

    # Build the "covers" clause from what ran, plus the still-excluded set.
    covered = ["filesystem inventory", "MACB timeline", "integrity verification"]
    if recovery_ran:
        covered.append("deleted/orphan-file recovery (data survival only)")
    if filtering_ran:
        covered.append("known-file filtering (NSRL/custom noise reduction)")
    if logs_ran:
        covered.append("log analysis merged into the super-timeline")
    if search_ran:
        covered.append("content search")

    excluded = []
    if not recovery_ran:
        excluded.append("deleted-file recovery")
    if not filtering_ran:
        excluded.append("known-file (NSRL) filtering")
    if not logs_ran:
        excluded.append("log analysis")
        excluded.append("super-timeline")
    if not search_ran:
        excluded.append("content search")

    covers_clause = (
        "This is an MVP report. It covers "
        + ", ".join(covered[:-1])
        + ", and "
        + covered[-1]
        + "."
    )
    if excluded:
        covers_clause += " It does NOT include " + ", ".join(excluded) + "."
    parts = [covers_clause]
    if recovery_ran:
        parts.append(
            "Recovered content is best-effort data survival only: ext4 clears "
            "block pointers on unlink and signature carving is deferred "
            "(CARVE-01), so a recovered file is not a guarantee the content is "
            "complete or unmodified, and a confidence tier makes no claim about "
            "who removed an entry or why."
        )
    if filtering_ran:
        parts.append(
            "Known-file filtering is examiner-supplied noise reduction, not a "
            "verdict: a hash match means the file is KNOWN to the supplied "
            "reference set — it does not assert the file is good or bad."
        )
    if logs_ran:
        parts.append(
            "Log analysis merges parsed system-log events into the UTC-ordered "
            "super-timeline; where a year or host timezone had to be inferred it "
            "is FLAGGED per event, not asserted as a recorded fact (D-46), and a "
            "log line is what the system recorded, not proof of who acted or why."
        )
    if search_ran:
        parts.append(
            "Content search reports byte-pattern matches at offsets — located "
            "evidence for review, not a judgement that a containing file is "
            "malicious."
        )
    parts.append("Absence of a finding here does not mean absence of evidence.")
    return " ".join(parts)


# Integrity copy strings, verbatim from 03-UI-SPEC.md:166-167, plus the honest
# "not supplied" state (WR-02). The PASS copy is only ever rendered when an
# acquisition hash was actually supplied AND matched; it never claims a hash
# match that did not happen (D-28 forbids overclaiming).
_INTEGRITY_PASS_COPY = (
    "Integrity verification: PASS — source hash matches acquisition value and "
    "end-of-run re-verification."
)
_INTEGRITY_FAIL_COPY = (
    "Integrity verification: FAIL — source hash mismatch. This report's findings "
    "may not correspond to the originally acquired evidence. Re-acquire and "
    "re-verify the source."
)
# No acquisition hash was supplied, so there was nothing to compare the source
# against. End-of-run re-verify still ran inside ingest (a readable, persisted
# source confirms the image was internally self-consistent), but the report must
# NOT claim a match against an acquisition value that was never provided (WR-02).
_INTEGRITY_NOT_SUPPLIED_COPY = (
    "Integrity verification: NOT COMPARED — no acquisition hash was supplied, so "
    "the source could not be compared against an acquisition value. End-of-run "
    "re-verification ran and the source read consistently, but no acquisition "
    "match is claimed."
)


def _is_deleted(file_row: FileRow) -> bool:
    """Return True for a deleted/unallocated entry (META-01/D-18, walk.py:555)."""
    return file_row.allocated is False


def _is_directory(file_row: FileRow) -> bool:
    """Return True when the entry's meta-type marks it a directory."""
    return file_row.meta_type == "dir"


def _recovered_section(file_row: FileRow) -> dict[str, Any]:
    """Project one recovered :class:`FileRow` to a plain, deterministic dict.

    Surfaces only data-survival facts (RECOV-01/03, D-32): the original path,
    confidence tier, recovered-bytes path, hashes, and the tier rationale +
    per-fs caveat lifted verbatim from ``attributes`` — never any intent or
    good/bad language. Carries no wall-clock (D-41).
    """
    attrs = file_row.attributes or {}
    rationale = attrs.get("recovery_tier_rationale")
    rationale_dict = rationale if isinstance(rationale, dict) else {}
    return {
        "meta_addr": file_row.meta_addr,
        "path": file_row.path,
        "confidence_tier": file_row.confidence_tier,
        "recovered_path": file_row.recovered_path,
        "md5": file_row.md5,
        "sha1": file_row.sha1,
        "sha256": file_row.sha256,
        "file_type": file_row.file_type,
        "tier_reason": rationale_dict.get("reason"),
        "tier_caveat": rationale_dict.get("caveat"),
    }


# Neutral intro for the Log Findings section (LOG-01/04, D-45/D-46). Like the
# known-file copy this is HONEST framing, not adjudication: a parsed log line is
# an evidence-recorded statement, and any inferred timezone/year is FLAGGED as an
# inference, never asserted as fact (D-46). Absence is not absence of evidence.
_LOG_FINDINGS_INTRO = (
    "Log Findings parses the image's system logs (auth/sudo/PAM and shell "
    "history) into the same UTC-ordered super-timeline as the filesystem MACB "
    "events (TIME-02). Each event carries its honest provenance: where a "
    "timezone or year had to be INFERRED (logs often omit the year and the host "
    "zone), that inference is flagged here and never presented as a recorded "
    "fact (D-46). A log line is what the system recorded — not proof of who "
    "acted or why."
)

# Neutral intro for the log honesty-disclosure sub-block (D-44/D-45). Like the
# known-file and log intros this is OBSERVED-FACT framing, never accusation or
# intent: a tamperability disclosure states only that shell history is editable
# by the subject and its line order is not chronological truth; a completeness
# disclosure states only which rotation indices were present/absent. The
# disclosure text itself is rendered VERBATIM from the parser/discover output.
_LOG_DISCLOSURE_INTRO = (
    "These are honesty disclosures about the parsed logs themselves, not "
    "findings against any person. A TAMPERABILITY disclosure records the "
    "observed fact that shell history is editable by the subject and its line "
    "order is therefore not chronological truth (D-44) — treat commands as "
    "observed evidence only, never as proof of timing or intent. A COMPLETENESS "
    "disclosure records which rotated-log indices were present or absent, so an "
    "incomplete log set is never presented as if it were the whole record (D-45)."
)

# Neutral intro for the Content Search section (SEARCH-01/02, D-49). A hit is a
# byte-pattern match at an offset — it is located evidence, not a verdict.
_SEARCH_INTRO = (
    "Content Search reports byte-pattern matches across allocated file content, "
    "unallocated space, and (for known-bad hash lists) the inventory's file "
    "hashes. A hit records WHAT matched and WHERE (volume, path, byte offset) — "
    "it is located evidence for the examiner to review, not a judgement that the "
    "containing file is malicious."
)


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
    store: CaseStore,
    evidence_source_id: int,
    *,
    acquisition_verified: bool | None = None,
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
        acquisition_verified: The real acquisition-compare outcome from ingest
            (``IngestResult.acquisition_verified``): ``True`` = an acquisition
            hash was supplied and matched, ``False`` = it was supplied and
            mismatched, ``None`` = none was supplied (nothing to compare). The
            report renders three honest states and NEVER claims a hash match that
            did not happen (WR-02 / D-28). Defaults to ``None`` (not compared) so
            a caller without the ingest result never overclaims a PASS.

    Returns:
        The analytical report body. Notable keys: ``case``, ``evidence``,
        ``header``, ``integrity``, ``methodology`` (pinned ``tsk_version`` +
        ``pyautopsy_version``), ``findings`` (D-28 inventory + integrity +
        limitations), ``evidence_hashes``, ``timeline`` (full, D-26 order),
        ``timeline_total`` (M = ``len(timeline)``, W-2) and ``limitations``.
        Carries NO ``run_metadata`` / ``generated_utc`` (D-25).
    """
    # Local import keeps the honesty-reviewed recovery copy as the single source
    # of truth in core/recover.py without a module-level report->core dependency.
    from pyautopsy.core.recover import RECOVERY_REPORT_COPY

    evidence = store.get_evidence_source(evidence_source_id)
    case = store.get_case(evidence.case_id)
    files = store.get_files(evidence_source_id)
    limitations = store.get_volume_limitations(evidence_source_id)
    events = store.get_timeline_events(evidence_source_id)
    # Recovered files + orphans, in the store's D-26 total order (never re-sorted
    # here — D-41). Orphans are a SEPARATE list (RECOV-02/D-25), never mixed into
    # the recovered list.
    recovered_files = store.get_recovered_files(evidence_source_id)
    orphan_files = store.get_orphan_files(evidence_source_id)
    # Neutral known-file annotations in the store's total order (never re-sorted
    # here — D-41); aggregated below into deterministic per-source/per-list counts.
    known_matches = store.get_known_matches(evidence_source_id)
    # Search hits in the store's D-41 total order (never re-sorted here). On the
    # default analyze path (no --search) this is empty, so the search section is
    # byte-identical across runs (CLI-02/D-48).
    search_hits = store.get_search_hits(evidence_source_id)
    # D-44/D-45 log honesty findings in the store's id order (never re-sorted
    # here — D-41). Empty on the default analyze path (no --logs), so the
    # disclosures sub-block renders as [] and the section stays byte-identical to
    # the Phase-4/05 baseline (D-48).
    log_findings_rows = store.get_log_findings(evidence_source_id)
    # (D-40 honesty) What this run actually covered, read from the case itself
    # rather than from caller-supplied flags. Each pass records its own stage as
    # it runs, so the report cannot under-claim (a caller forgetting a flag) or
    # over-claim (a caller passing one for a pass that did not run). Crucially
    # this is NOT inferred from whether a pass produced rows: a search that ran
    # and matched nothing still covered the image, and must be reported as such.
    stages = store.stages_run(evidence.case_id)

    # -- Inventory aggregation set (BL-01): exclude recovered rows ---------------
    # The walk records every deleted inode as a ``files`` row (allocated=False,
    # recovered=NULL). When ``--recover`` runs, run_recover inserts a SECOND row
    # for the same inode (allocated=False, recovered=1). Since ``_is_deleted``
    # only tests ``allocated is False``, both rows would be counted — inflating
    # file_count/deleted_count/per_volume/file_type_distribution by exactly the
    # number of recovered inodes. Recovered/orphan inodes are surfaced in their
    # OWN report sections (``recovered``/``orphans`` below), so they must NOT also
    # be aggregated into the inventory. Filter them out once here; the recovered/
    # orphan/known sections read their own store queries and are unaffected. This
    # stays deterministic (filter preserves the store's D-26 order) and keeps the
    # default analyze path (no recovered rows) byte-identical to Phase 3 (D-40).
    inventory_files = [f for f in files if f.recovered is not True]

    # -- Findings 4a: inventory counts (deterministic; no iteration-order deps) --
    file_count = len(inventory_files)
    directory_count = sum(1 for f in inventory_files if _is_directory(f))
    deleted_count = sum(1 for f in inventory_files if _is_deleted(f))

    # -- Findings 4b: per-volume breakdown, sorted by (volume_id, volume_offset) --
    volume_acc: dict[tuple[int, int], dict[str, Any]] = {}
    for f in inventory_files:
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
        # WR-03: prefer a non-null fs_type over a null one so the report never
        # shows a blank fs for a volume that clearly has one just because the
        # first row seen (get_files id order) happened to be a meta-less/orphan
        # entry. First non-null wins; later differing non-null values do not
        # silently overwrite (deterministic, order-stable).
        if bucket["fs_type"] is None and f.fs_type is not None:
            bucket["fs_type"] = f.fs_type
        bucket["file_count"] += 1
        if _is_deleted(f):
            bucket["deleted_count"] += 1
    per_volume = [volume_acc[key] for key in sorted(volume_acc)]

    # -- Findings 4c: file-type distribution, ranked by (-count, type) -----------
    type_counter: Counter[str] = Counter(
        f.file_type for f in inventory_files if f.file_type is not None
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

    # -- Log Findings (LOG-01/04, D-45/D-46) -------------------------------------
    # The merged super-timeline IS `timeline` above (the get_timeline_events read,
    # TIME-02 — NO new ORDER BY here). This section surfaces the LOG slice of that
    # same total order plus its honest tamperability/completeness provenance. A
    # log event is any event whose source is not the filesystem MACB source
    # (filesystem events use a `filesystem`/`filesystem:<fs>` label); the filter
    # preserves the store's D-26 order so the section stays byte-stable, and is
    # empty on the default analyze path so report bytes are unchanged (D-48).
    log_events = [ev for ev in events if not ev.source.startswith("filesystem")]
    # Per-source counts (e.g. auth / syslog / shell-history), ranked by
    # (-count, source) so the breakdown is deterministic regardless of insert
    # order; the source labels are content-derived, not wall-clock.
    log_source_counter: Counter[str] = Counter(ev.source for ev in log_events)
    log_by_source = [
        {"source": source, "count": count}
        for source, count in sorted(
            log_source_counter.items(), key=lambda item: (-item[1], item[0])
        )
    ]
    # Honest provenance flags (D-46): how many log events relied on an INFERRED
    # timezone or year. These are surfaced as a completeness/tamperability caveat,
    # never erased — the report must not present an inferred time as recorded
    # fact. Derived deterministically by counting attribute presence.
    inferred_year_count = sum(
        1 for ev in log_events if (ev.attributes or {}).get("year_inferred") is not None
    )
    inferred_tz_count = sum(
        1
        for ev in log_events
        if (ev.attributes or {}).get("assumed_timezone") is not None
    )
    # D-44/D-45 honesty disclosures: one dict per persisted finding row, in the
    # store's id order (never re-sorted here — D-41; mirrors limitation_rows). On
    # the default path get_log_findings is [], so this is [] and the section is
    # byte-identical to the Phase-4/05 baseline (D-48).
    disclosures = [
        {
            "category": row.category,
            "subject": row.subject,
            "detail": row.detail,
        }
        for row in log_findings_rows
    ]
    log_findings = {
        "intro": _LOG_FINDINGS_INTRO,
        "count": len(log_events),
        "by_source": log_by_source,
        "disclosures_intro": _LOG_DISCLOSURE_INTRO,
        "disclosures": disclosures,
        "provenance": {
            "inferred_year_count": inferred_year_count,
            "inferred_timezone_count": inferred_tz_count,
            "caveat": (
                "Where a year or host timezone was inferred (logs frequently omit "
                "the year and the host zone), each affected event carries that "
                "inference as a flag in the super-timeline — it is not asserted as "
                "a recorded fact (D-46). Absence of a log finding does not mean "
                "absence of evidence."
            ),
        },
    }

    # -- Content Search (SEARCH-01/02, D-49): per-region/per-kind counts ---------
    # Read in the store's D-41 total order (never re-sorted here). Counts are
    # ranked by sorted keys so the section is byte-stable across runs; the
    # `term` bytes are decoded latin-1 (lossless round-trip) for display so a
    # non-UTF-8 needle never crashes the body. Empty on the default path (D-48).
    search_region_counter: Counter[str] = Counter(h.region for h in search_hits)
    search_by_region = [
        {"region": region, "count": count}
        for region, count in sorted(
            search_region_counter.items(), key=lambda item: (-item[1], item[0])
        )
    ]
    search_kind_counter: Counter[str] = Counter(h.term_kind for h in search_hits)
    search_by_kind = [
        {"term_kind": kind, "count": count}
        for kind, count in sorted(
            search_kind_counter.items(), key=lambda item: (-item[1], item[0])
        )
    ]
    search_results = [
        {
            "term": h.term.decode("latin-1"),
            "term_kind": h.term_kind,
            "region": h.region,
            "volume_id": h.volume_id,
            "volume_offset": h.volume_offset,
            "byte_offset": h.byte_offset,
            "path": h.path,
            # A bounded surrounding-bytes snippet (data only; the HTML autoescapes
            # it, Security V5 / threat T-05-04-02). May be None.
            "context": h.context,
        }
        for h in search_hits
    ]

    # -- Known-File Filtering (noise reduction): per-source/per-list counts ------
    # Deterministic aggregation: NSRL matches by which hash matched, and custom
    # matches grouped by (list_name, sense). Counters are ranked by sorted keys
    # so the section is byte-stable across runs (D-41); neutral framing only —
    # no good/bad/clean/malicious language (D-38).
    nsrl_match_count = sum(1 for m in known_matches if m.source == "nsrl")
    nsrl_matched_on: Counter[str] = Counter(
        m.matched_on for m in known_matches if m.source == "nsrl"
    )
    custom_acc: dict[tuple[str, str], int] = {}
    for m in known_matches:
        if m.source != "custom":
            continue
        custom_key = (m.list_name or "", m.sense or "")
        custom_acc[custom_key] = custom_acc.get(custom_key, 0) + 1
    custom_lists: list[dict[str, Any]] = [
        {
            "list_name": list_name,
            "sense": sense,
            "count": custom_acc[(list_name, sense)],
        }
        for (list_name, sense) in sorted(custom_acc)
    ]
    custom_match_count = sum(int(item["count"]) for item in custom_lists)
    known_file_ids = {m.file_id for m in known_matches}

    # Derive the THREE honest integrity states from the real ingest outcome
    # (WR-02) — never a hardcoded PASS:
    #   acquisition_verified is True  -> hash supplied AND matched (PASS)
    #   acquisition_verified is None  -> no hash supplied (NOT COMPARED)
    #   acquisition_verified is False -> hash supplied but mismatched (FAIL)
    # End-of-run re-verify always ran inside ingest and the source persisted (a
    # FAIL there raises + rolls back), so reverify_pass is True for any reachable
    # report. acquisition_compare_pass is True ONLY when a match actually
    # happened, so the report never claims "source hash matches acquisition
    # value" when no acquisition hash was supplied (D-28 no-overclaim).
    if acquisition_verified is False:
        acquisition_compare_pass = False
        overall_pass = False
        integrity_copy = _INTEGRITY_FAIL_COPY
    elif acquisition_verified is True:
        acquisition_compare_pass = True
        overall_pass = True
        integrity_copy = _INTEGRITY_PASS_COPY
    else:  # None — no acquisition hash supplied, nothing to compare against
        acquisition_compare_pass = False
        overall_pass = True
        integrity_copy = _INTEGRITY_NOT_SUPPLIED_COPY
    reverify_pass = True
    acquisition_supplied = acquisition_verified is not None

    return {
        # 1. Header / identity band
        # NOTE: ``acquired_utc`` / ``created_utc`` are wall-clock chain-of-custody
        # timestamps (assigned at ingest time, store.py:207/iso_utc) and are run
        # metadata, not analytical content. They are deliberately EXCLUDED from
        # the body so two runs serialize byte-identically (CLI-02 / D-25): they
        # are surfaced via the ``reports/run_metadata.json`` sidecar instead
        # (W-1), exactly as test_reproducibility classifies them
        # (_RUN_METADATA_COLUMNS). Including them here is a determinism leak.
        "header": {
            "title": f"PyAutopsy Forensic Report — Case {case.id}",
            "case_id": case.id,
            "case_name": case.name,
            "examiner": case.examiner,
            "evidence_id": evidence.evidence_id,
            "acquisition_source": evidence.path,
            "image_type": evidence.image_type,
        },
        # Convenience top-level COC handles (also consumed by the JSON readers).
        "case": {
            "id": case.id,
            "name": case.name,
            "examiner": case.examiner,
            "notes": case.notes,
        },
        "evidence": {
            "id": evidence.id,
            "evidence_id": evidence.evidence_id,
            "path": evidence.path,
            "image_type": evidence.image_type,
            "byte_size": evidence.byte_size,
            # Evidence digests are analytical (a pure function of the source
            # bytes), so they stay in the reproducible body — unlike the
            # wall-clock acquired_utc above.
            "md5": evidence.md5,
            "sha256": evidence.sha256,
        },
        # 2. Integrity verification (prominent; three honest states, WR-02)
        "integrity": {
            "acquisition_supplied": acquisition_supplied,
            "acquisition_compare_pass": acquisition_compare_pass,
            "reverify_pass": reverify_pass,
            "passed": overall_pass,
            "copy": integrity_copy,
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
                "acquisition_supplied": acquisition_supplied,
                "acquisition_compare_pass": acquisition_compare_pass,
                "reverify_pass": reverify_pass,
                "passed": overall_pass,
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
        # 6a. Recovered files (RECOV-01/03, D-32/D-41) — data survival only, no
        # intent/good-bad copy; ordered by the store, no wall-clock.
        "recovered": {
            "intro": RECOVERY_REPORT_COPY["section_intro"],
            "tier_copy": {
                "intact": RECOVERY_REPORT_COPY["tier_intact"],
                "partial/overwritten": RECOVERY_REPORT_COPY["tier_partial_overwritten"],
            },
            "files": [_recovered_section(f) for f in recovered_files],
            "count": len(recovered_files),
        },
        # 6b. Orphan files (RECOV-02/D-25) — reported SEPARATELY from recovered.
        "orphans": {
            "intro": RECOVERY_REPORT_COPY["orphan_intro"],
            "files": [_recovered_section(f) for f in orphan_files],
            "count": len(orphan_files),
        },
        # 6c. Known-File Filtering (noise reduction, FILTER-01/D-38) — neutral
        # membership annotations only; deterministic per-source/per-list counts,
        # no good/bad/verdict, no wall-clock.
        "known": {
            "intro": _KNOWN_FILTER_INTRO,
            "files_matched": len(known_file_ids),
            "nsrl": {
                "count": nsrl_match_count,
                "matched_on": [
                    {"hash": hash_col, "count": count}
                    for hash_col, count in sorted(
                        nsrl_matched_on.items(),
                        key=lambda item: (-item[1], item[0]),
                    )
                ],
            },
            "custom": {
                "count": custom_match_count,
                "lists": custom_lists,
            },
        },
        # 6d. Log Findings (LOG-01/04, D-45/D-46) — the LOG slice of the merged
        # super-timeline (`timeline` above is that merged read, TIME-02) plus its
        # honest inferred-time provenance. Empty on the default path (D-48).
        "log_findings": log_findings,
        # 6e. Content Search (SEARCH-01/02, D-49) — byte-pattern hits by region/
        # kind; located evidence, not a verdict. Empty on the default path (D-48).
        "search": {
            "intro": _SEARCH_INTRO,
            "count": len(search_results),
            "by_region": search_by_region,
            "by_kind": search_by_kind,
            "hits": search_results,
        },
        # 7. Limitations: D-20 volumes + the honest MVP disclaimer (mandatory).
        # The disclaimer reflects what ACTUALLY ran (D-40): default-path text is
        # byte-identical to Phase 3; it is rewritten only when recovery/filtering
        # ran so it never denies a capability that ran (D-28/D-32).
        "limitations": {
            "volumes": limitation_rows,
            "mvp_disclaimer": _mvp_limitations(
                recovery_ran=Stage.RECOVER in stages,
                filtering_ran=Stage.FILTER in stages,
                logs_ran=Stage.LOGS in stages,
                search_ran=Stage.SEARCH in stages,
            ),
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
            "Run Metadata (non-analytical — excluded from the reproducible report body)"
        ),
        "generated_utc": generation_ts,
        "host": host,
        "durations": durations,
        "run_id": run_id,
    }
