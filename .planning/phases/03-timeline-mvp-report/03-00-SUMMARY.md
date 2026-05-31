---
phase: 03-timeline-mvp-report
plan: 00
subsystem: database
tags: [sqlite, timeline, forensic-event-model, jinja2, pytest, tdd, determinism]

# Dependency graph
requires:
  - phase: 01-forensic-foundation
    provides: CaseStore single-writer abstraction, Case/EvidenceSource COC models, transaction(), _commit_unless_in_transaction, _load_attributes, audit log
  - phase: 02-filesystem-walk-metadata
    provides: FileRow with UTC MACB *_utc columns + volume/path/meta_addr/uid/gid, run_walk/run_ingest orchestrators, VolumeLimitation findings
provides:
  - "timeline_events table (shared forensic-event model D-23) with the D-26 ordering index + per-source index"
  - "TimelineEvent frozen-slots dataclass (D-24 field shape) re-exported from pyautopsy.case"
  - "CaseStore.insert_timeline_events / get_timeline_events (D-26 total order, optional limit) — the single read-ordering site"
  - "jinja2 declared as a pure-Python dependency (REPORT-03/D-22)"
  - "RED test scaffolds (canonical node IDs) for TIME-01, REPORT-03, REPORT-04, CLI-01, CLI-02"
affects: [03-timeline-builder, 03-reporter, 03-analyze-cli, 05-log-super-timeline]

# Tech tracking
tech-stack:
  added: ["jinja2>=3.1,<4 (declared; not yet imported)"]
  patterns:
    - "Shared forensic-event model: one timeline_events table, fs MACB is first producer, Phase 5 log producers reuse the shape (D-23)"
    - "D-26 total order defined exactly once in get_timeline_events ORDER BY (no raw SQL elsewhere)"
    - "Module-level _TIMELINE_COLUMNS + derived _TIMELINE_INSERT_SQL + _timeline_event_params, mirroring the _FILES_* pattern"
    - "Value-level (not structural) ordering tests on a deliberately-tied fixture (W-3 / Nyquist)"

key-files:
  created:
    - tests/test_timeline.py
    - tests/test_report.py
    - tests/test_analyze.py
  modified:
    - src/pyautopsy/case/schema.sql
    - src/pyautopsy/case/models.py
    - src/pyautopsy/case/__init__.py
    - src/pyautopsy/case/store.py
    - tests/test_case_store.py
    - tests/test_reproducibility.py
    - pyproject.toml

key-decisions:
  - "actor encoded as 'uid=<n>,gid=<n>' for filesystem events (RESEARCH A4); action/outcome reserved for Phase 5 log producers"
  - "source label 'filesystem:<fs_type>' (falls back to 'filesystem') per D-23 discretion"
  - "Declared known-first-party=[pyautopsy,tests] in ruff isort so RED scaffolds importing not-yet-created first-party packages sort cleanly"

patterns-established:
  - "Forensic-event blackboard table consumed by both the reporter (this phase) and Phase 5 log producers"
  - "Single canonical D-26 sort site in the store; builder/reporter never re-sort or write raw SQL"
  - "RED Wave-0 scaffolds use canonical node IDs and fail on ImportError/missing-command (never skipped)"

requirements-completed: []  # Wave 0 establishes contracts + RED bar; requirements close in later waves

# Metrics
duration: ~20min
completed: 2026-05-31
---

# Phase 3 Plan 00: Timeline Contract Surface & RED Test Scaffold Summary

**Added the `timeline_events` shared forensic-event table (D-23/D-24), the `TimelineEvent` model, and the D-26 totally-ordered `CaseStore` insert/read path — plus declared Jinja2 and authored value-level RED tests for all five Phase 3 requirements.**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-05-31T12:21Z
- **Completed:** 2026-05-31T12:41Z
- **Tasks:** 2
- **Files modified:** 10 (3 created, 7 modified)

## Accomplishments
- `timeline_events` table + `idx_timeline_events_order` (D-26) + `idx_timeline_events_evidence_source_id` present in a freshly created `case.db`, mirroring the `files` block conventions (typed core + JSON `attributes`, NOT NULL volume columns per WR-06, nullable `file_id` for Phase 5 log events).
- `TimelineEvent` frozen-slots dataclass (D-24 field shape: required typed fields first, `None`-defaulted optionals, `attributes`+`id` last) with a full Args docstring; re-exported from `pyautopsy.case`.
- `CaseStore.insert_timeline_events` (bulk `executemany`, composes inside an outer `transaction()`) and `get_timeline_events` — the SINGLE site of the D-26 total order (`ts_utc → volume_id → volume_offset → path → event_type → meta_addr`), with an optional `limit` for the D-27 bounded HTML slice. No raw SQL outside `store.py`.
- Jinja2 declared (`jinja2>=3.1,<4`) — pure-Python, D-14 native seam untouched.
- RED scaffolds with the canonical node IDs from the RESEARCH Test Map: `test_macb_explosion`, `test_total_order` (value-level on a tied fixture, W-3), `test_ext4_timeline`, `test_json_report`, `test_html_autoescape`, `test_html_truncation_note`, `test_findings_d28`, `test_fat_provenance`, `test_versions_recorded`, `test_analyze_produces_reports`, `test_analyze_composes_pipeline`, and the CLI-02 `test_two_analyze_runs_byte_identical_report` (whole-file byte-equality on BOTH report.json and report.html; run_metadata.json segregated and asserted to differ).

## Task Commits

Each task was committed atomically:

1. **Task 1: timeline_events schema + TimelineEvent model + store CRUD with D-26 ordered read** - `2019e6f` (feat) — TDD: RED test (ImportError) → GREEN implementation in one feat commit (test + impl staged together since the new tests live in the existing `test_case_store.py`).
2. **Task 2: Declare jinja2 + author failing RED tests for all Phase 3 requirements** - `d8b9e5f` (test)

**Plan metadata:** (this commit)

## Files Created/Modified
- `src/pyautopsy/case/schema.sql` - Added `timeline_events` table + two indexes (D-23/D-24/D-26).
- `src/pyautopsy/case/models.py` - Added `TimelineEvent` frozen-slots dataclass; added it to `__all__`.
- `src/pyautopsy/case/__init__.py` - Re-exported `TimelineEvent`.
- `src/pyautopsy/case/store.py` - Added `insert_timeline_events` / `get_timeline_events` + `_TIMELINE_COLUMNS` / `_TIMELINE_INSERT_SQL` / `_timeline_event_params`.
- `tests/test_case_store.py` - GREEN CRUD tests + value-level D-26 total-order + limit tests for the new store path.
- `tests/test_timeline.py` (new) - RED: MACB explosion, value-level total order, ext4 integration (TIME-01).
- `tests/test_report.py` (new) - RED: JSON body, HTML autoescape, truncation note, D-28 findings, FAT provenance, versions recorded (REPORT-03/04).
- `tests/test_analyze.py` (new) - RED: `analyze` produces reports + composes the pipeline (CLI-01).
- `tests/test_reproducibility.py` - Added `_analyze` helper + `test_two_analyze_runs_byte_identical_report` (CLI-02/W-1).
- `pyproject.toml` - Declared `jinja2>=3.1,<4`; declared `known-first-party=[pyautopsy,tests]` for isort.

## Decisions Made
- `actor` encoded as `"uid=<n>,gid=<n>"` for filesystem events (RESEARCH A4); `action`/`outcome` reserved (NULL) for Phase 5 log producers.
- `source` label `"filesystem:<fs_type>"` with a `"filesystem"` fallback (D-23 discretion).
- The D-26 `ORDER BY` lives only in `get_timeline_events`; the builder/reporter (later waves) must read through it and never re-sort or write raw SQL.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Declared `known-first-party` for ruff isort**
- **Found during:** Task 2 (RED test authoring)
- **Issue:** The RED scaffolds import not-yet-created first-party packages (`pyautopsy.timeline`, `pyautopsy.report`). Ruff isort classified them as third-party (they do not yet exist on disk), splitting the import block and failing `ruff check` (I001) — a blocking lint gate for the phase.
- **Fix:** Added `[tool.ruff.lint.isort] known-first-party = ["pyautopsy", "tests"]` so all in-repo imports group together regardless of on-disk existence. Survives once the later-wave modules land.
- **Files modified:** pyproject.toml
- **Verification:** `ruff check tests/ src/pyautopsy/case pyproject.toml` → No issues found.
- **Committed in:** d8b9e5f (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Config-only adjustment required to keep the lint gate green for RED scaffolds that intentionally import future packages. No scope creep; no behavior change.

## Issues Encountered
- The combined full-suite `pytest -q` run aborts on collection because the RED modules `test_timeline.py`/`test_report.py` raise `ModuleNotFoundError` for the not-yet-built `pyautopsy.timeline`/`pyautopsy.report` packages. This is the intended Wave-0 RED state (the plan's own verification runs the RED files separately with `|| true`). Existing suites run green in isolation: `test_cli_smoke + test_ingest + test_walk + test_case_store` → 61 passed.

## Verification Evidence
- `python -m pytest tests/test_case_store.py -q` → 22 passed (timeline CRUD + value-level D-26 order + limit).
- `ruff check src/pyautopsy/case && mypy src/pyautopsy/case` → clean (mypy: No issues found across `src`).
- `grep "import pytsk3\|import pyewf" src/pyautopsy/case/store.py src/pyautopsy/case/models.py` → no matches (D-14 native seam untouched).
- New RED files fail for the right reason: `test_timeline`/`test_report` ImportError on missing downstream modules; `test_analyze`/repro byte-identical fail at runtime on "No such command 'analyze'".
- `grep "jinja2" pyproject.toml` → matches in `[project.dependencies]`.
- Existing suites green: `python -m pytest tests/test_cli_smoke.py tests/test_ingest.py tests/test_walk.py tests/test_case_store.py -q` → 61 passed.

## Known Stubs
None. This plan delivers a complete, exercised contract surface (the store CRUD is green-tested) plus intentional RED scaffolds. The RED tests are not stubs — they are the executable acceptance bar that later waves drive green (per 03-VALIDATION.md). No hardcoded empty/placeholder values flow to any rendered output (no rendering exists yet).

## User Setup Required
None - no external service configuration required. (jinja2 is already importable in the environment, 3.1.6.)

## Next Phase Readiness
- The `timeline_events` schema, `TimelineEvent` model, and D-26-ordered store read/write API are the contracts Waves 1–3 build against:
  - Wave 1 `timeline/builder.py` (`build_timeline` + `explode`) writes via `insert_timeline_events`.
  - Wave 2 `report/` (`assemble_report_body`, `write_json`, `render_html`) reads via `get_timeline_events` (full for JSON, `limit=cap` for the bounded HTML).
  - Wave 3 `core/analyze.py` + the `analyze` CLI command compose `run_ingest`→`run_walk`→`build_timeline`→`render_report`.
- The RED node IDs are the green target; CLI-02's `test_two_analyze_runs_byte_identical_report` is the gating reproducibility check.
- No blockers.

---
*Phase: 03-timeline-mvp-report*
*Completed: 2026-05-31*

## Self-Check: PASSED
- All created/modified files verified present on disk.
- Task commits `2019e6f` and `d8b9e5f` verified in git history.
