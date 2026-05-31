---
phase: 03-timeline-mvp-report
plan: 03
subsystem: orchestration
tags: [analyze, cli, end-to-end, reproducibility, determinism, fresh-case, sidecar, self-audit]

# Dependency graph
requires:
  - phase: 03-timeline-mvp-report
    plan: 00
    provides: "RED test_analyze.py + CLI-02 RED test_reproducibility.py (byte-identical report set); timeline_events table"
  - phase: 03-timeline-mvp-report
    plan: 01
    provides: "build_timeline(store, esid) -> event count (MACB explosion)"
  - phase: 03-timeline-mvp-report
    plan: 02
    provides: "assemble_report_body / build_run_metadata / write_json / render_html (render_html takes NO run_metadata, W-1)"
  - phase: 02-filesystem-walk-metadata
    provides: "run_walk orchestrator + WalkResult/WalkError; _EXPECTED_WALK_ERRORS pattern"
  - phase: 01-forensic-foundation
    provides: "run_ingest orchestrator (end-of-run re-verify inside it) + IngestResult/IngestError; CaseStore.open; AuditLog; util.timeutil utc_now/iso_utc"
provides:
  - "pyautopsy.core.analyze exporting run_analyze, AnalyzeResult, AnalyzeError"
  - "run_analyze(image, case_dir, *, examiner, evidence_id, acquisition_hash=None, timezone='UTC', max_hash_size=None) -> AnalyzeResult — full ingest→walk→timeline→report pipeline in one process (CLI-01)"
  - "fresh-case guard (AnalyzeError if case.db exists, A2) + analyze.start/end/error/crashed self-audit (REPORT-02)"
  - "run metadata written ONLY to reports/run_metadata.json sidecar (W-1); report.json + report.html whole-file byte-deterministic across runs (CLI-02)"
  - "pyautopsy analyze CLI command (full D-21 option surface), thin shell mapping forensic failures to the integrity exit code"
affects: [04-recovery-findings, 05-log-super-timeline]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Orchestrator composition: run_analyze drives run_ingest then run_walk then build_timeline+report renderers — composes the existing orchestrators, never re-implements the native seam (D-14); imports no pytsk3/pyewf"
    - "_EXPECTED_ANALYZE_ERRORS tuple mirrors walk's _EXPECTED_WALK_ERRORS: expected operational failures get an analyze.error FAIL audit + re-raise; genuine bugs get a DISTINCT analyze.crashed event"
    - "Wall-clock segregation (D-25/W-1): the only now()/iso_utc site in the pipeline feeds build_run_metadata, written to the run_metadata.json sidecar with the json.dumps(sort_keys, ensure_ascii=False) idiom — never the body, never render_html"
    - "Fresh-case (A2): refuse to run if case.db exists, BEFORE binding the audit log or doing any work"

key-files:
  created:
    - src/pyautopsy/core/analyze.py
  modified:
    - src/pyautopsy/core/__init__.py
    - src/pyautopsy/cli/main.py
    - src/pyautopsy/report/assemble.py
    - src/pyautopsy/report/templates/report.html.j2

key-decisions:
  - "Wall-clock COC timestamps (acquired_utc/created_utc) removed from the report body — they are run metadata (test_reproducibility already classifies them as _RUN_METADATA_COLUMNS) and remain authoritative in case.db; analytical evidence md5/sha256 digests added to the body's evidence section instead"
  - "report.html.j2 body.integrity.copy resolved the dict's built-in .copy METHOD (leaking a per-run memory address); switched to item access body.integrity[\"copy\"] — the correct fix at the reporter source, not a test loosening"
  - "run_analyze binds the AuditLog only AFTER run_ingest (which creates the case dir + logs/ layout); the fresh-case guard runs before that, so the case dir need not pre-exist"
  - "durations left empty ({}) in build_run_metadata for the MVP — the timestamp + host already make run_metadata.json volatile (CLI-02 asserts generated_utc differs); per-stage timing is a non-blocking later enhancement"

# Metrics
metrics:
  duration: "~25 min"
  completed: 2026-05-31
  tasks_completed: 2
  files_created: 1
  files_modified: 4
  commits: 3
  tests_passing: 171
---

# Phase 3 Plan 3: Single-Command Analyze + Reproducibility Summary

`pyautopsy analyze <image> --case ...` now runs the entire MVP vertical slice in one process — composing `run_ingest` (with its Phase 1 end-of-run re-verify) + `run_walk` + `build_timeline` + the report renderers — and two runs on the same fixture produce whole-file byte-identical `report.json` AND `report.html`, with all volatile run metadata segregated to the `reports/run_metadata.json` sidecar (CLI-01 + CLI-02 / W-1).

## What was built

- **`core/analyze.py`** (`run_analyze` / `AnalyzeResult` / `AnalyzeError`): the single-command orchestrator. Fresh-case guard (A2) refuses to run into an existing `case.db` before any work; composes the existing orchestrators (re-verify runs inside `run_ingest`); builds the timeline + report set through one open store; writes the run-metadata sidecar as the only wall-clock site; `analyze.start/end` self-audit plus `analyze.error`/`analyze.crashed` FAIL events; analytical-only `AnalyzeResult`. Imports no native bindings (D-14).
- **`analyze` CLI command** (full D-21 surface: `--case --examiner --evidence-id --acquisition-hash --timezone --max-hash-size`): up-front timezone validation, forensic failures mapped to the integrity exit code after the orchestrator FAIL audit, concise summary echoing both report paths. `ingest`/`walk` untouched.

## Verification

- `python -m pytest -q` → **171 passed**; `ruff check .` clean; `mypy src` clean.
- `tests/test_analyze.py` (both node IDs) GREEN; `tests/test_reproducibility.py::test_two_analyze_runs_byte_identical_report` GREEN — whole-file byte-equality on report.json AND report.html, `run_metadata.json` excluded and asserted to differ.
- `ingest`/`walk` standalone tests unaffected (no regression).
- Acceptance greps confirmed: composition of all four (`run_ingest`/`run_walk`/`build_timeline`/`assemble_report_body`); `run_metadata.json`/`build_run_metadata` present; `render_html` called WITHOUT a run_metadata argument; no `pytsk3`/`pyewf` import.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Wall-clock COC timestamps leaked into the reproducible report body**
- **Found during:** Task 2 (CLI-02 byte-equality assertion on report.json failed)
- **Issue:** `assemble_report_body` (03-02) put `evidence.acquired_utc` and `case.created_utc` — wall-clock chain-of-custody timestamps assigned at ingest time — into the body's `header`/`case`/`evidence` sections, so report.json differed between runs.
- **Fix:** Removed those keys from the body (they are run metadata, already classified as `_RUN_METADATA_COLUMNS` by `test_reproducibility`, and remain authoritative in `case.db`); added the analytical `md5`/`sha256` evidence digests to the body's evidence section (also satisfies the CLI-02 sanity assert `body["evidence"]["sha256"]`).
- **Files modified:** `src/pyautopsy/report/assemble.py`
- **Commit:** 71a4b9c

**2. [Rule 1 - Bug] HTML template leaked a per-run memory address (`body.integrity.copy`)**
- **Found during:** Task 2 (CLI-02 byte-equality assertion on report.html failed)
- **Issue:** `report.html.j2` used `{{ body.integrity.copy }}`; Jinja attribute lookup resolved the dict's built-in `.copy` *method* (not the `"copy"` key), rendering `<built-in method copy of dict object at 0x...>` — a different address each run.
- **Fix:** Switched to item access `{{ body.integrity["copy"] }}` so the integrity copy string renders deterministically.
- **Files modified:** `src/pyautopsy/report/templates/report.html.j2`
- **Commit:** 71a4b9c

Both leaks were fixed at the reporter source per the plan's explicit instruction (no test loosening, no moving run metadata into report.html).

## Authentication Gates

None.

## Known Stubs

- `build_run_metadata` is called with `durations={}` (empty). This is intentional for the MVP: the generation timestamp + host already make `run_metadata.json` volatile (CLI-02 asserts `generated_utc` differs between runs). Per-stage duration timing is a non-blocking later enhancement, not required by CLI-01/CLI-02.

## Self-Check: PASSED

- FOUND: src/pyautopsy/core/analyze.py
- FOUND commit c287308 (feat: run_analyze orchestrator)
- FOUND commit 71a4b9c (fix: report-body determinism leaks)
- FOUND commit 818a9c5 (feat: analyze CLI command)
