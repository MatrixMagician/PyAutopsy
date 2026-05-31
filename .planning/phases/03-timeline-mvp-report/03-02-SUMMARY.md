---
phase: 03-timeline-mvp-report
plan: 02
subsystem: report
tags: [report, jinja2, autoescape, determinism, bounded-timeline, forensic-honesty, path-confinement]

# Dependency graph
requires:
  - phase: 03-timeline-mvp-report
    plan: 00
    provides: "timeline_events table + CaseStore.get_timeline_events (D-26 order), TimelineEvent model, jinja2 declared, RED test_report.py"
  - phase: 03-timeline-mvp-report
    plan: 01
    provides: "build_timeline producer — rows the reporter reads back via get_timeline_events"
  - phase: 02-filesystem-walk-metadata
    provides: "FileRow with allocated/meta_type/file_type/volume + attributes provenance flags (time_precision/assumed_timezone/file_type_provenance); VolumeLimitation D-20 findings; EvidenceSource md5/sha256/tsk_version; run_walk/run_ingest"
  - phase: 01-forensic-foundation
    provides: "CaseStore read API (get_case/get_evidence_source/get_files/get_volume_limitations), audit/log.py _is_within path-confinement primitive, Case.pyautopsy_version"
provides:
  - "pyautopsy.report package exporting assemble_report_body, build_run_metadata, write_json, render_html"
  - "assemble_report_body(store, esid) -> deterministic 8-section body dict incl. FULL D-26 timeline + timeline_total (M); NO wall-clock reachable (D-25)"
  - "build_run_metadata(...) -> segregated volatile run-metadata dict (sole wall-clock site; consumed by 03-03 sidecar)"
  - "write_json(body, case_dir) -> reports/report.json (sort_keys, ensure_ascii=False, no trailing newline, confined)"
  - "render_html(body, case_dir, *, cap=2000) -> reports/report.html (autoescaped, in-process bounded slice, honest truncation, no run metadata, confined)"
  - "report.html.j2 self-contained offline template (8 sections, inline CSS, A4 print rules)"
affects: [03-analyze-cli, 04-recovery-findings, 05-log-super-timeline]

# Tech tracking
tech-stack:
  added: []  # jinja2 was already declared in 03-00; first IMPORTED here
  patterns:
    - "Pattern 3 determinism single-source-of-truth: one assemble_report_body dict feeds both JSON (full timeline) and HTML (in-process bounded slice); wall-clock segregated to build_run_metadata"
    - "Jinja2 offline+autoescaped env (select_autoescape html/j2, trim_blocks, lstrip_blocks, keep_trailing_newline) located via importlib.resources.files — deterministic whitespace + escaped evidence values"
    - "Path confinement reuses audit/log.py _is_within realpath guard for reports/ (same idiom as the audit log + exports)"
    - "In-process bounded timeline: body holds the full D-26 list + timeline_total (M); render_html slices [:cap] with no store handle (W-2)"

key-files:
  created:
    - src/pyautopsy/report/__init__.py
    - src/pyautopsy/report/assemble.py
    - src/pyautopsy/report/jsonreport.py
    - src/pyautopsy/report/htmlreport.py
    - src/pyautopsy/report/templates/report.html.j2
  modified: []

key-decisions:
  - "Body carries BOTH the plan's 8 canonical-section keys (header/integrity/methodology/findings/evidence_hashes/timeline/limitations) AND the RED test's required top-level handles (case/evidence/timeline_total); reconciled by emitting both — no behavior conflict, the test keys are convenience COC handles alongside the header band"
  - "Integrity = PASS for any persisted evidence source: run_ingest raises + rolls back on any acquisition-compare or end-of-run re-verify FAIL, so a readable EvidenceSource is provably post-PASS. Booleans + both UI-SPEC copy strings are still emitted so the renderer is honest if a future producer persists a FAIL row"
  - "EvidenceSource has no sha1 column (only md5/sha256 for the source image); evidence_hashes.sha1 is None and the template renders '(not computed)' rather than fabricating a hash"
  - "reports/ subdir is created in the reporter (jsonreport._confined_reports_dir) via the _is_within + mkdir idiom, NOT by editing store.py's _SUBDIRS — keeps file ownership disjoint from Wave 0 (per the plan's resolved note)"
  - "Provenance flags surfaced as DISTINCT deterministically-sorted flag-sets (not one row per file) so FAT local-time-inferred / assumed_timezone survive to the report (Pitfall 10) without per-file noise"

requirements-completed: [REPORT-03, REPORT-04, CLI-02]

# Metrics
duration: ~5min
completed: 2026-05-31
---

# Phase 3 Plan 02: Deterministic Reporter (JSON + HTML) Summary

**Added the `pyautopsy.report` package — `assemble_report_body` builds ONE wall-clock-free 8-section body dict (full D-26 timeline + `timeline_total`); `write_json` emits the unabridged sorted-key UTF-8 JSON and `render_html` renders an autoescaped, offline, bounded-timeline HTML with an honest "Showing N of M" disclosure and ZERO run metadata — turning all six RED `test_report.py` cases GREEN.**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-05-31T12:48:51Z
- **Tasks:** 2
- **Files modified:** 5 (5 created, 0 modified)

## Accomplishments

- **`assemble_report_body(store, esid)`** reads the COC (`get_evidence_source` → `get_case`), the walk inventory (`get_files`), the D-20 limitations (`get_volume_limitations`) and the FULL D-26-ordered timeline (`get_timeline_events`, no limit), then returns a fixed-key dict covering the eight canonical UI-SPEC sections. D-28 findings = inventory counts (file/dir/deleted via `allocated is False`), per-volume breakdown sorted by `(volume_id, volume_offset)`, file-type distribution ranked by `(-count, type)`, integrity PASS/FAIL, and limitations. FAT `time_precision`/`assumed_timezone` + `file_type_provenance` are lifted out of `FileRow.attributes` and surfaced. `timeline_total = len(timeline)` (M) is carried so HTML discloses honestly without a store handle (W-2). No `datetime.now`/`utc_now`/`iso_utc` is reachable (verified by grep).
- **`build_run_metadata(...)`** is the segregated, sole wall-clock site (D-25) — never merged into the body, never passed to `render_html`; 03-03 writes it to the `run_metadata.json` sidecar.
- **`write_json(body, case_dir)`** serializes with `json.dumps(sort_keys=True, ensure_ascii=False)`, no trailing newline (locked convention), confined to `case_dir/reports/` via the reused `audit/log.py:_is_within` realpath guard; path built only from `case_dir` + the fixed name (Pitfall 4).
- **`render_html(body, case_dir, *, cap=2000)`** builds the offline autoescaped Jinja2 env (`select_autoescape(["html","j2"])`, `trim_blocks`, `lstrip_blocks`, `keep_trailing_newline`) via `importlib.resources.files`, slices `body["timeline"][:cap]` in-process (NO store handle, W-2), and renders the disclosure only when `timeline_total > N`. Takes NO run-metadata argument (W-1); output confined to `reports/`.
- **`report.html.j2`** is a self-contained offline template: one inline `<style>`, system-font stacks, 8 sections in canonical order, text+glyph status encoding (PASS ✓ / FAIL ✗ / provenance ⚠ / limitation), prominent integrity card near the top, timeline table in D-26 column order, mandatory Limitations section + standing MVP disclaimer, `@page { size: A4; margin: 16mm; }` + `@media print`, `overflow-wrap: anywhere` on hashes/paths. No `| safe`/`Markup()`, no http(s)/CDN/`@import`/web-font, no viewport units, no run-metadata footer.
- The `.j2` template ships in the built wheel by default (verified: `pyautopsy/report/templates/report.html.j2` present in `pyautopsy-0.1.0-py3-none-any.whl`) — no `pyproject.toml` `force-include`/`artifacts` entry was needed.

## Task Commits

Each task was committed atomically:

1. **Task 1: deterministic report body + JSON writer** - `0be8d39` (feat) — TDD GREEN. The RED `test_report.py` (committed in 03-00, `d8b9e5f`) failed to collect on `ModuleNotFoundError: pyautopsy.report`; this commit lands `__init__.py` + `assemble.py` + `jsonreport.py` (and a placeholder `htmlreport.py` so the package `__init__` re-exports resolve), turning `test_json_report`/`test_findings_d28`/`test_fat_provenance`/`test_versions_recorded` GREEN. No separate RED commit was needed (the RED test predates this plan).
2. **Task 2: autoescaped offline HTML report + bounded timeline** - `64b88cf` (feat) — TDD GREEN: replaces the Task-1 `render_html` placeholder with the real Jinja2 renderer + authors `report.html.j2`, turning `test_html_autoescape`/`test_html_truncation_note` GREEN.

**Plan metadata:** (final docs commit)

## Files Created/Modified

- `src/pyautopsy/report/__init__.py` (new) — Reporter package; exports `assemble_report_body`, `build_run_metadata`, `write_json`, `render_html`.
- `src/pyautopsy/report/assemble.py` (new) — `assemble_report_body` (8-section deterministic body, full timeline + `timeline_total`, D-28 findings, surfaced provenance, pinned versions) + `build_run_metadata` (segregated volatile dict).
- `src/pyautopsy/report/jsonreport.py` (new) — `write_json` + `_confined_reports_dir` (`_is_within` realpath confinement + `mkdir`).
- `src/pyautopsy/report/htmlreport.py` (new) — `render_html` + `_build_env`; in-process bounded slice, no run metadata, confined.
- `src/pyautopsy/report/templates/report.html.j2` (new) — self-contained offline 8-section template with print rules.

## Decisions Made

- The body emits BOTH the plan's 8 canonical-section keys AND the RED test's required top-level handles (`case`, `evidence`, `timeline_total`) — the test keys are convenience COC handles emitted alongside the `header` band; no conflict.
- Integrity is PASS for any persisted evidence source (ingest rolls back on FAIL), but the body still carries PASS/FAIL booleans + both UI-SPEC copy strings so a future FAIL-persisting producer renders honestly.
- `evidence_hashes.sha1 = None` (the `EvidenceSource` source-image record has no sha1 column — only md5/sha256); the template renders `(not computed)` rather than fabricating a value.
- `reports/` is created in the reporter (not by editing `store.py:_SUBDIRS`), keeping Wave-0 file ownership disjoint (per the plan's resolved note).

## Deviations from Plan

None — plan executed as written. (Emitting both the plan's section keys and the RED test's `case`/`evidence`/`timeline_total` top-level keys is not a deviation: the plan's own `<acceptance_criteria>` requires the `timeline_total` key and the RED test — authored in 03-00 — asserts `case`/`evidence`, so both are required for the stated GREEN bar.)

## Known Stubs

None. `assemble_report_body`/`write_json`/`render_html` are fully wired end-to-end and exercised by the now-GREEN `test_report.py` on real ext4/FAT32 fixtures (ingest → walk → build_timeline → assemble → render). The `build_run_metadata` function is intentionally NOT called here — it is consumed by 03-03 (the `analyze` orchestrator + sidecar), which is the next plan; this is documented above, not a stub.

## Threat Flags

None. No security-relevant surface beyond the plan's `<threat_model>`. T-03-06 (autoescape of evidence values) is verified by `test_html_autoescape` + the `| safe`/`Markup()` grep; T-03-07 (path confinement) reuses the audited `_is_within` guard; T-03-08 (bounded HTML) by the in-process `[:cap]` slice; T-03-09 (truncation honesty) by `test_html_truncation_note` + the mandatory Limitations section; T-03-10 (no non-deterministic markup) by the wall-clock grep + no run-metadata footer.

## Verification Evidence

- `python -m pytest tests/test_report.py -q` → **6 passed** (`test_json_report`, `test_html_autoescape`, `test_html_truncation_note`, `test_findings_d28`, `test_fat_provenance`, `test_versions_recorded`).
- Regression: `python -m pytest tests/test_case_store.py tests/test_walk.py tests/test_ingest.py tests/test_cli_smoke.py tests/test_timeline.py tests/test_report.py -q` → **70 passed** (64 baseline + 6 report; no regressions).
- `ruff check src/pyautopsy/report` → All checks passed. `mypy src/pyautopsy/report` → Success: no issues found in 4 source files.
- `grep -n "datetime.now\|utc_now\|iso_utc" src/pyautopsy/report/assemble.py` → no matches (no wall-clock in the body).
- `grep -c "def assemble_report_body(\|def build_run_metadata(" src/pyautopsy/report/assemble.py` → 2; `timeline_total` present.
- `grep "json.dumps(" src/pyautopsy/report/jsonreport.py` → `sort_keys=True, ensure_ascii=False`.
- `grep "select_autoescape(" src/pyautopsy/report/htmlreport.py` → present; `body["timeline"][:cap]` sliced in-process.
- `grep -n "run_metadata" src/pyautopsy/report/htmlreport.py src/pyautopsy/report/templates/report.html.j2` → no matches (W-1).
- `grep -n "| safe\|Markup(" .../report.html.j2` → none; `grep -n "http://\|https://\|@import\|//cdn"` → none; `grep "[0-9]vh\|[0-9]vw\|[0-9]vmin"` → no viewport units.
- Wheel packaging: built `pyautopsy-0.1.0-py3-none-any.whl` contains `pyautopsy/report/templates/report.html.j2` (template ships by default; no pyproject change needed). Build artifacts removed afterward.

## Next Phase Readiness

- 03-03 (`analyze` CLI + sidecar) composes `run_ingest → run_walk → build_timeline → assemble_report_body → write_json → render_html`, then calls `build_run_metadata(...)` and writes the `reports/run_metadata.json` sidecar — driving `test_analyze.py` and the CLI-02 `test_two_analyze_runs_byte_identical_report` (both `report.json` and `report.html` are now whole-file byte-deterministic, since neither carries run metadata).
- The HTML/JSON report shell is the surface Phase 4 (recovery findings) and Phase 5 (log/search findings) extend additively.
- No blockers.

---
*Phase: 03-timeline-mvp-report*
*Completed: 2026-05-31*

## Self-Check: PASSED
- All five created files verified present on disk (`report/__init__.py`, `assemble.py`, `jsonreport.py`, `htmlreport.py`, `templates/report.html.j2`).
- Task commits `0be8d39` and `64b88cf` verified in git history.
