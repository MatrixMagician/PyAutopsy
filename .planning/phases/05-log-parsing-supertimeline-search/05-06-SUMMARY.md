---
phase: 05-log-parsing-supertimeline-search
plan: 06
subsystem: testing
tags: [fixtures, ground-truth, year-inference, rfc3164, ext4, regression-guard]

# Dependency graph
requires:
  - phase: 05-log-parsing-supertimeline-search
    provides: "05-05 G-2 gap closure (D-44/D-45 log_findings); the committed log_search_ext4.img fixture + its D-46 mtime-anchored year inference (_seed_year_from_mtime)"
provides:
  - "log_search_groundtruth.json year/prev_year reconciled to the years the committed fixture actually produces (2023 / 2022)"
  - "make_fixtures.py LOG_SEARCH_YEAR/PREV_YEAR anchored to _EXT4_FAKE_TIME=1700000000 with an explanatory comment"
  - "test_groundtruth_year_matches_fixture_mtime: a regression guard pinning the sidecar year to the fixture's real mtime anchor"
affects: [verification, human-uat, phase-close]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Fixture/sidecar reconciliation (Path B): align the documented ground truth to the value the committed evidence carries rather than rebuilding the evidence — preserves the image sha256 forensic baseline"
    - "Guard test reads the year_inferred attribute (the D-46 RFC3164 year), NOT the tz-converted ts_utc calendar year, to avoid the late-December host-tz UTC-boundary artifact"

key-files:
  created: []
  modified:
    - tests/fixtures/make_fixtures.py
    - tests/fixtures/log_search_groundtruth.json
    - tests/test_logs.py

key-decisions:
  - "Path B chosen (reconcile sidecar/constants to 2023/2022) over Path A (rebuild image to ~Jan-2026): Path B leaves the committed .img bytes + sha256 (6e41afad...079b0) untouched, so UAT test 11's read-only baseline and every hash assertion stay valid with NO lockstep edit."
  - "Confirmed inferred year by computation: datetime.fromtimestamp(1700000000, utc).year = 2023 (2023-11-14); live members -> 2023, oldest rotated Dec member -> 2022. Matches the plan's expected 2023/2022."
  - "Guard test pins year_inferred (the sidecar-documented RFC3164 year), not the UTC-year of ts_utc: a Dec 31 23:59:59 America/New_York line converts to 2024-01-01T04:59:59Z, a tz artifact whose year_inferred is correctly 2023."

patterns-established:
  - "Year-inference fixtures document the inferred RFC3164 year (year_inferred), kept distinct from the tz-converted UTC instant which can cross a calendar-year boundary at the host tz."

requirements-completed: [TIME-02, LOG-01, LOG-02]

# Metrics
duration: ~18min
completed: 2026-06-01
---

# Phase 05 Plan 06: Fixture/Sidecar Year Reconciliation (G-1) Summary

**Closed UAT gap G-1 by reconciling log_search_groundtruth.json and make_fixtures.py to the 2023/2022 years the committed ext4 fixture's frozen-clock (_EXT4_FAKE_TIME=1700000000) mtime anchor actually yields, plus a year_inferred guard test — image bytes and sha256 left untouched.**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-06-01
- **Completed:** 2026-06-01
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Retargeted `LOG_SEARCH_YEAR = 2023` / `LOG_SEARCH_PREV_YEAR = 2022` in make_fixtures.py, anchored by a comment to the committed image's frozen debugfs clock `_EXT4_FAKE_TIME = 1700000000` (2023-11-14 UTC).
- Regenerated `log_search_groundtruth.json` (`year` 2026→2023, `prev_year` 2025→2022), byte-consistent with `_groundtruth_dict()` (`json.dumps(..., indent=2, sort_keys=True) + "\n"`).
- Added `test_groundtruth_year_matches_fixture_mtime` — a regression guard that drives the real ingest+walk+run_logs path over the committed fixture and asserts every inferred RFC3164 event's `year_inferred` is in `{prev_year, year}` with `year` actually produced, so the drift cannot silently return.
- Verified the committed image bytes and sha256 (`6e41afad...079b0`) are UNCHANGED — no rebuild, no UAT-test-11 baseline lockstep.

## Task Commits

Each task was committed atomically:

1. **Task 1: Reconcile fixture-anchored years (Path B)** - `5670ccd` (fix)
2. **Task 2: Guard test pinning the sidecar year to the fixture mtime anchor** - `cc2ce16` (test)

**Plan metadata:** (final docs commit — see completion notes)

## Files Created/Modified
- `tests/fixtures/make_fixtures.py` - `LOG_SEARCH_YEAR`/`LOG_SEARCH_PREV_YEAR` retargeted to 2023/2022 with an `_EXT4_FAKE_TIME` anchor comment; `_EXT4_FAKE_TIME` and image build path untouched.
- `tests/fixtures/log_search_groundtruth.json` - `year`→2023, `prev_year`→2022; regenerated from the corrected constants, byte-equal to `_groundtruth_dict()`.
- `tests/test_logs.py` - new `test_groundtruth_year_matches_fixture_mtime` regression guard (additive; no existing test edited).

## Decisions Made
- **Path B over Path A.** Reconcile the documentation sidecar + generator constants to the fixture's real mtime anchor instead of rebuilding the image to a ~Jan-2026 fake clock. Path A would churn the committed `.img` sha256 and force a lockstep update of UAT test 11's read-only baseline and every hash assertion; Path B touches only docs/constants/test and keeps the forensic baseline valid.
- **Pin on `year_inferred`, not the UTC year of `ts_utc`.** The fixture's `Dec 31 23:59:59` America/New_York line converts to `2024-01-01T04:59:59Z`; its UTC calendar year (2024) is a tz artifact, while `year_inferred` (2023) is the value the generator and sidecar agree on. The guard reads `year_inferred` so it pins the documented inference, not a tz boundary side effect.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Guard test asserted on the wrong year attribute (initial draft)**
- **Found during:** Task 2 (guard test, RED phase)
- **Issue:** The first draft of `test_groundtruth_year_matches_fixture_mtime` derived the year from the calendar year of the tz-converted `ts_utc`. The fixture's `Dec 31 23:59:59` America/New_York line resolves to `2024-01-01T04:59:59Z`, so the UTC-year (2024) fell outside the sidecar's `{2022, 2023}` and the test failed even against the corrected sidecar (a false negative — the data was correct, the assertion was measuring a tz artifact).
- **Fix:** Changed the guard to read each inferred event's `year_inferred` attribute (the D-46 RFC3164 year the sidecar documents) instead of the UTC calendar year of `ts_utc`. Added a docstring note explaining the late-December host-tz UTC-boundary distinction.
- **Files modified:** tests/test_logs.py
- **Verification:** GREEN against the corrected 2023/2022 sidecar; RED re-confirmed against a temporarily drifted 2026/2025 sidecar (`inferred years [2024]`/[2023, 2024] not in allowed set). Full suite 220 passed.
- **Committed in:** `cc2ce16` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug, caught and fixed within the TDD RED phase before commit)
**Impact on plan:** The fix corrected the guard's measurement basis to the inference the plan intended to pin (`year_inferred`); no scope change. The plan's expected 2023/2022 values were confirmed by computation, matching exactly.

## Issues Encountered
- The fixture genuinely produces a UTC year of 2024 for one late-December event (the host-tz boundary crossing described above). This is expected forensic behaviour, not a bug — surfaced and handled by pinning the guard on `year_inferred`. No change to inference logic was made (the mechanism was already sound; this plan is reconciliation only).

## TDD Gate Compliance
Task 2 was `tdd="true"`. As a guard test over data corrected in Task 1, the RED/GREEN cycle was demonstrated in-process (RED: failed against a 2026/2025-drifted sidecar; GREEN: passed against the corrected 2023/2022 sidecar) and the additive test landed in a single `test(...)` commit (`cc2ce16`), with the corrective implementation (sidecar/constants) in the prior `fix(...)` commit (`5670ccd`). No separate feat gate applies — the implementation under guard is fixture data, not new behaviour.

## Verification Evidence
- `sha256sum tests/fixtures/log_search_ext4.img` → `6e41afadc5309b4471e2c2377e8022104510d84ec8c6b18ececa10f2901079b0` (UNCHANGED — no rebuild).
- `git status --porcelain` task changes limited to `make_fixtures.py`, `log_search_groundtruth.json`, `test_logs.py` (NOT the `.img`).
- Regenerated sidecar byte-equals the committed `log_search_groundtruth.json` (`_groundtruth_dict()` round-trip → BYTE-CONSISTENT).
- `infer_years` mechanism unit tests (test_logs.py:371-417) and literal-2026 serialization tests (test_logs.py:146/159, test_reproducibility.py:435) UNCHANGED.
- `PYTHONPATH=src python -m pytest -q` → 220 passed (was 219; +1 guard test).

## Next Phase Readiness
- G-1 documentation drift closed; the log/search corpus now self-documents the years D-46 truly infers, with a guard preventing recurrence.
- Phase 05 plan counter advances to 7 of 7. Remaining: phase-close / verification reconciliation (no further gap-closure plans outstanding from this UAT).

## Self-Check: PASSED

- FOUND: `.planning/phases/05-log-parsing-supertimeline-search/05-06-SUMMARY.md`
- FOUND: commit `5670ccd` (Task 1)
- FOUND: commit `cc2ce16` (Task 2)

---
*Phase: 05-log-parsing-supertimeline-search*
*Completed: 2026-06-01*
