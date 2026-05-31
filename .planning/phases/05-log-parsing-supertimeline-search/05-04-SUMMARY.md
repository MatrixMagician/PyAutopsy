---
phase: 05-log-parsing-supertimeline-search
plan: 04
subsystem: api
tags: [analyze, super-timeline, logs, search, reproducibility, jinja2, sqlite, determinism]

# Dependency graph
requires:
  - phase: 05-01
    provides: run_logs orchestrator (auth/syslog/shell-history parsers, discover, timeresolve, normalize) writing log events into timeline_events
  - phase: 05-03
    provides: run_search orchestrator + get_search_hits store read + search_hits table
  - phase: 04
    provides: run_analyze opt-in pattern (recover/filter), assemble_report_body, byte-deterministic report set + run_metadata sidecar
provides:
  - "analyze --logs / --search opt-in arms wired into run_analyze (mirror recover/filter), with counts in AnalyzeResult and new flags in the analyze.start audit"
  - "report body Log Findings + Content Search sections; super-timeline stays the existing get_timeline_events read (TIME-02, no new ORDER BY)"
  - "honest MVP disclaimer rebuilt when logs/search ran; default path byte-identical (CLI-02/D-48)"
  - "reproducibility regressions: merged super-timeline byte-stability + direct CR-01 NULL-meta tied-log-event tiebreak"
affects: [reporting, timeline, end-to-end-pipeline, future-phases-consuming-analyze]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Opt-in feature arms in run_analyze gated on a per-feature flag; default path stays byte-identical (D-40/D-48)"
    - "New report sections derive only from store-owned total-order reads (get_timeline_events / get_search_hits); no wall-clock in the body (Pitfall 6)"
    - "event_count read back from get_timeline_events after both opt-in passes (super-timeline total = the store-owned read, TIME-02)"

key-files:
  created:
    - .planning/phases/05-log-parsing-supertimeline-search/05-04-SUMMARY.md
  modified:
    - src/pyautopsy/core/analyze.py
    - src/pyautopsy/cli/main.py
    - src/pyautopsy/report/assemble.py
    - src/pyautopsy/report/templates/report.html.j2
    - tests/test_reproducibility.py

key-decisions:
  - "Ran build_timeline BEFORE the log/search opt-in arms so run_logs' idempotent fs-event backfill is a no-op (no double-insert); event_count is then read from get_timeline_events (the store-owned super-timeline order), never recomputed."
  - "Added a direct store-level CR-01 test (test_tied_log_events_null_meta_tiebreak) because run_logs currently surfaces only auth events on the fixture (syslog tied lines are not yet merged by run_logs), so the fixture-driven byte-identity test alone would not exercise a real NULL-meta tie. The store-level test inserts two tied log events (same ts/vol/path/type, NULL meta, differing only in source/actor) and asserts a stable total order regardless of insertion order."
  - "assemble_report_body gained logs_ran/search_ran flags (default False) so the MVP disclaimer is honest about what ran while the default-path disclaimer text is byte-identical to the Phase-4 baseline."
  - "report.html.j2 template references body keys explicitly, so Log Findings + Content Search sections were added as new template blocks (empty-state on the default path keeps default HTML byte-identical)."

patterns-established:
  - "Pattern: super-timeline total = len(store.get_timeline_events(source_id)) read once after opt-in passes (TIME-02; no new ORDER BY anywhere)."
  - "Pattern: report sections render an empty-state when their store read is empty, so the default path emits byte-identical report.json/report.html."

requirements-completed: [LOG-01, LOG-02, LOG-03, LOG-04, TIME-02, SEARCH-01, SEARCH-02]

# Metrics
duration: 35min
completed: 2026-05-31
---

# Phase 5 Plan 04: Wave-3 Integration (logs + search into analyze + report) Summary

**The single `pyautopsy analyze --logs --search <term>` command now emits one report with the merged filesystem+log super-timeline (TIME-02), a Log Findings section, and a Content Search section — while default `analyze` stays byte-identical to the Phase-4 baseline (CLI-02/D-48), with CR-01 tied-log-event determinism locked.**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-05-31T18:36Z
- **Completed:** 2026-05-31T19:11Z
- **Tasks:** 2
- **Files modified:** 5 (4 src/test + this summary)

## Accomplishments
- Wired `logs: bool` + `search: str | None` opt-in arms into `run_analyze`, mirroring the existing recover/filter opt-in: each sub-orchestrator runs ONLY when its flag is set, forwarding `evidence_source_id=source_id`, with new counts (`log_events`, `search_hits`) in `AnalyzeResult` and the new flags recorded in the `analyze.start` audit — no wall-clock added.
- Added Log Findings + Content Search sections to `assemble_report_body`, derived purely from store-owned total-order reads (`get_timeline_events` log slice + `get_search_hits`); no `utc_now()` in the body. The super-timeline is the existing `get_timeline_events` read (TIME-02) — no new ORDER BY anywhere.
- Rebuilt the MVP-limitations disclaimer to be honest about logs/search when they ran, while keeping the default-path disclaimer byte-identical (D-48).
- Added `--logs` / `--search` flags to the `analyze` Typer command (mirroring recover/nsrl) and Log Findings + Content Search HTML template sections (autoescaped, empty-state on default path).
- Locked determinism: a fixture-driven `test_tied_log_events_stable` (two `analyze --logs` runs → byte-identical merged super-timeline) plus a direct `test_tied_log_events_null_meta_tiebreak` proving the CR-01 source/actor/id tiebreak orders tied NULL-meta log events deterministically regardless of insertion order.

## Task Commits

1. **Task 1: wire --logs/--search opt-in into analyze + report sections** - `fcd607a` (feat)
2. **Task 2: reproducibility + super-timeline determinism regression tests** - `3409d07` (test)

_TDD note: the test_analyze.py / test_report.py scaffolds already existed and passed against the new wiring; the genuinely-new RED→GREEN determinism tests are Task 2's `test_reproducibility.py` additions._

## Files Created/Modified
- `src/pyautopsy/core/analyze.py` - `logs`/`search` params + opt-in arms; `log_events`/`search_hits` in `AnalyzeResult`; new audit flags; `event_count` read from `get_timeline_events`; `logs_ran`/`search_ran` passed to assemble.
- `src/pyautopsy/cli/main.py` - `analyze --logs` / `--search` flags; `LogsError`/`SearchError` in the except tuple; log/search count summary lines.
- `src/pyautopsy/report/assemble.py` - Log Findings + Content Search section builders (store-ordered, no wall-clock); honest disclaimer rebuild with `logs_ran`/`search_ran`.
- `src/pyautopsy/report/templates/report.html.j2` - Log Findings + Content Search HTML sections (autoescaped, empty-state default).
- `tests/test_reproducibility.py` - `test_tied_log_events_stable` + `test_tied_log_events_null_meta_tiebreak`; `CaseStore` import.

## Decisions Made
- See `key-decisions` in frontmatter. The load-bearing ones: order build_timeline before the opt-in passes (no double-insert), and add a direct store-level CR-01 tie test because run_logs does not yet merge the fixture's syslog tied lines.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Avoided timeline double-insert when --logs is set**
- **Found during:** Task 1 (wiring the log arm)
- **Issue:** `run_logs` has an idempotent guard that backfills filesystem MACB events when none exist. If the log arm ran before `build_timeline`, fs events would be inserted twice (once by run_logs' backfill, once by build_timeline), corrupting the super-timeline.
- **Fix:** Run `build_timeline(store, source_id)` FIRST, then the log/search arms; run_logs' backfill then sees existing events and is a no-op. `event_count` is read from `get_timeline_events` after both passes.
- **Files modified:** src/pyautopsy/core/analyze.py
- **Verification:** End-to-end `analyze --logs --search` produces 77 events = 68 fs + 9 log (no duplication); full suite GREEN.
- **Committed in:** fcd607a

**2. [Rule 2 - Missing Critical] Direct CR-01 NULL-meta tiebreak test**
- **Found during:** Task 2 (writing test_tied_log_events_stable)
- **Issue:** The plan's `test_tied_log_events_stable` assumes run_logs surfaces the fixture's tied syslog lines, but run_logs currently merges only auth events on this fixture — so the fixture-driven byte-identity test would not actually exercise a real NULL-meta tie (risk of a false pass on the headline CR-01 invariant).
- **Fix:** Kept the fixture-driven byte-identity test AND added `test_tied_log_events_null_meta_tiebreak` that inserts two tied log events (same ts/vol/path/type, NULL meta, differing only in source/actor) directly via the store and asserts a stable total order independent of insertion order (auth < syslog).
- **Files modified:** tests/test_reproducibility.py
- **Verification:** Both tests pass; the store-level test fails if the source/actor/id tiebreak regresses.
- **Committed in:** 3409d07

---

**Total deviations:** 2 auto-fixed (1 bug, 1 missing-critical test).
**Impact on plan:** Both necessary for correctness/determinism integrity. No scope creep — the wiring and section shape are exactly as the plan specified.

## Issues Encountered
- run_logs opens its own CaseStore connection while the analyze read-back store is also open. No SQLite lock conflict observed (build_timeline commits before the log arm opens its connection); verified end-to-end.

## Threat Flags
None — no new security surface beyond the plan's threat register. Evidence strings (log lines, search terms/context) render through jinja2 autoescape (T-05-04-02 mitigated); the report body carries no wall-clock (T-05-04-01 mitigated); D-46 inferred-time provenance is surfaced as a flagged caveat, never as fact (T-05-04-03 mitigated); zero new runtime deps, test_no_new_deps GREEN (T-05-04-SC / D-43).

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 5 closed: the full "image + logs → defensible report" pipeline is one command with byte-stable output. All 7 phase requirements (LOG-01..04, TIME-02, SEARCH-01/02) are observable end-to-end.
- Full suite GREEN (208 passed); ruff + mypy clean on src; no-new-deps gate GREEN.
- Known follow-up (NOT a blocker for this plan): run_logs surfaces only auth events on the current fixture; merging the fixture's syslog tied lines into run_logs would let `test_tied_log_events_stable` exercise the live tie in addition to the store-level test. Tracked as a Wave-1/2 parser concern, not Wave-3 integration.

---
*Phase: 05-log-parsing-supertimeline-search*
*Completed: 2026-05-31*

## Self-Check: PASSED

All created/modified files exist on disk; both task commits (fcd607a, 3409d07) are present in git history.
