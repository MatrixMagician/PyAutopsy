---
phase: 03-timeline-mvp-report
plan: 01
subsystem: timeline
tags: [timeline, macb-explosion, forensic-event-model, producer, tdd, determinism]

# Dependency graph
requires:
  - phase: 03-timeline-mvp-report
    plan: 00
    provides: "timeline_events table (D-23/D-24), TimelineEvent model, CaseStore.insert_timeline_events / get_timeline_events (D-26 ordered), RED test_timeline.py"
  - phase: 02-filesystem-walk-metadata
    provides: "FileRow with UTC MACB *_utc columns + volume/path/meta_addr/uid/gid/fs_type, run_walk orchestrator, CaseStore.get_files"
provides:
  - "timeline package (pyautopsy.timeline) exporting build_timeline + explode"
  - "build_timeline(store, evidence_source_id) -> int: first producer into the shared forensic-event table (MACB explosion of files rows, persisted in one transaction)"
  - "_explode/explode pure transform: FileRow -> one TimelineEvent per populated *_utc column (D-24)"
affects: [03-reporter, 03-analyze-cli, 05-log-super-timeline]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "MACB explosion producer (ARCHITECTURE Pattern 1): module-level _MACB map + pure _explode mapper + thin transaction shell, mirroring core/walk.py's _build_file_row + run_walk split"
    - "ts_utc copied verbatim from the walk's *_utc columns; the builder re-derives no timestamps (T-03-04)"
    - "Producer writes through the store inside one transaction; no native bindings, no raw SQL"

key-files:
  created:
    - src/pyautopsy/timeline/__init__.py
    - src/pyautopsy/timeline/builder.py
  modified: []

key-decisions:
  - "Canonical transform is _explode (satisfies the acceptance grep `def _explode(`); a module-level `explode = _explode` alias is exported so the RED test's `from pyautopsy.timeline.builder import explode` resolves without a second definition"
  - "_explode sets file_id=file_row.id so filesystem events carry their FK into files (D-23 evidence-ref); actor/source derived once per row before the MACB loop"

patterns-established:
  - "First concrete producer of the shared forensic-event blackboard table; Phase 5 log producers reuse the same TimelineEvent shape and the same store insert path"
  - "Builder never re-sorts and never writes raw SQL — the D-26 total order lives only in CaseStore.get_timeline_events"

requirements-completed: [TIME-01]

# Metrics
duration: ~10min
completed: 2026-05-31
---

# Phase 3 Plan 01: Timeline Builder (MACB Explosion Producer) Summary

**Added the `pyautopsy.timeline` package with `build_timeline` — the first producer into the shared `timeline_events` table: it reads Phase 2 `files` rows and explodes each populated MACB timestamp into one normalized `TimelineEvent` (D-24), copying `ts_utc` verbatim and persisting through the store in a single transaction — turning the RED `test_timeline.py` GREEN.**

## Performance

- **Duration:** ~10 min
- **Tasks:** 1
- **Files modified:** 2 (2 created, 0 modified)

## Accomplishments
- `src/pyautopsy/timeline/builder.py`: a pure `_explode(file_row) -> list[TimelineEvent]` mapper plus a thin `build_timeline(store, evidence_source_id) -> int` orchestrator. The mapper derives `actor` (`uid=<n>,gid=<n>` when either is known, else `None`) and `source` (`filesystem:<fs_type>`, falling back to `filesystem`) once per row, then for each `(col, etype)` in the module-level `_MACB` map reads `getattr(file_row, col)`, skips `None` (D-24: 0-epoch already mapped to `None` upstream, so no extra logic), and otherwise appends a `TimelineEvent` with `ts_utc` copied **verbatim** and `file_id=file_row.id`.
- `build_timeline` reads `store.get_files(evidence_source_id)`, explodes each row, and bulk-inserts via `store.insert_timeline_events(events)` inside one `with store.transaction():`, returning the analytical-only event count (no wall-clock metadata, mirroring `WalkResult`).
- `src/pyautopsy/timeline/__init__.py` exports `build_timeline` and `explode`, mirroring `core/__init__.py`'s `__all__` style.
- The producer imports no native bindings (`pytsk3`/`pyewf`), contains no raw SQL (writes through the store), and re-derives no timestamps (no `from_epoch_utc`/`iso_utc`/`datetime.now`) — satisfying the T-03-04/T-03-03 mitigations in the threat register.

## Task Commits

Each task was committed atomically:

1. **Task 1: build_timeline producer — MACB explosion into timeline_events** - `5f9f4d6` (feat) — TDD GREEN: the RED scaffold (`test_timeline.py`, authored in 03-00) was already on disk and failed to collect (ImportError on the missing `pyautopsy.timeline`); this commit lands the implementation that turns it GREEN. No separate RED commit was needed (the RED test was committed in 03-00, `d8b9e5f`).

**Plan metadata:** (final docs commit)

## Files Created/Modified
- `src/pyautopsy/timeline/__init__.py` (new) - Timeline package; exports `build_timeline` + `explode`.
- `src/pyautopsy/timeline/builder.py` (new) - `_MACB` map, pure `_explode` mapper (with `explode` alias), `build_timeline` transaction shell.

## Decisions Made
- The canonical transform is `_explode` (satisfies the acceptance grep `def _explode(`); `explode = _explode` is exported so the RED test's `from pyautopsy.timeline.builder import explode` resolves without duplicating the function. The plan's `<action>` named `_explode` while the RED `<behavior>`/test imports `explode` — the alias reconciles both without deviation to behavior.
- `_explode` sets `file_id=file_row.id` so filesystem events carry their FK into `files` (D-23 evidence-ref). `actor`/`source` are derived once per row before the MACB loop (not re-computed per column).

## Deviations from Plan
None — plan executed as written. (The `explode`-vs-`_explode` reconciliation is an alias, not a behavior/scope change: the plan's own RED test imports `explode`, so exposing it is required for the test to pass; the private `_explode` name satisfies the acceptance grep.)

## Known Stubs
None. `build_timeline` is fully wired end-to-end (files -> explosion -> store insert) and exercised by the now-GREEN `test_ext4_timeline` integration test on the committed ext4 fixture.

## Threat Flags
None. No new security-relevant surface beyond the plan's `<threat_model>`. T-03-04 (verbatim `ts_utc`, no re-derivation) and T-03-03 (no native seam) are verified by grep gates below; T-03-05 (no silently-dropped events) is guarded by the value-level explosion/ordering tests.

## Verification Evidence
- `python -m pytest tests/test_timeline.py -x -q` -> **3 passed** (`test_macb_explosion`, `test_total_order`, `test_ext4_timeline`).
- `python -m pytest tests/test_case_store.py tests/test_walk.py tests/test_ingest.py tests/test_cli_smoke.py tests/test_timeline.py -q` -> **64 passed** (61 baseline + 3 new timeline; no regressions).
- `ruff check src/pyautopsy/timeline` -> No issues found.
- `mypy src/pyautopsy/timeline` -> No issues found.
- `grep -n "import pytsk3\|import pyewf\|datetime.now\|from_epoch_utc\|iso_utc" src/pyautopsy/timeline/builder.py` -> no matches (no native seam, no timestamp re-derivation).
- `grep -v '^#' src/pyautopsy/timeline/builder.py | grep -c "execute(\|executemany("` -> 0 (no raw SQL — writes via the store).
- `grep -n "def build_timeline(\|def _explode(" src/pyautopsy/timeline/builder.py` -> both present.

## Next Phase Readiness
- `build_timeline` is the producer Wave 2 (`report/`) consumes via `store.get_timeline_events` (full for JSON, `limit=cap` for the bounded HTML), and Wave 3 (`core/analyze.py` + the `analyze` CLI) composes `run_ingest` -> `run_walk` -> `build_timeline` -> `render_report`.
- The shared `TimelineEvent` shape and store insert path are exactly what Phase 5 log producers reuse additively (no schema churn).
- No blockers.

---
*Phase: 03-timeline-mvp-report*
*Completed: 2026-05-31*

## Self-Check: PASSED
- All created files verified present on disk (`timeline/__init__.py`, `timeline/builder.py`, `03-01-SUMMARY.md`).
- Task commit `5f9f4d6` verified in git history.
