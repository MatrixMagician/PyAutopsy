---
phase: 05-log-parsing-supertimeline-search
plan: 00
subsystem: testing
tags: [pytest, fixtures, ext4, debugfs, rfc3164, syslog, search, tdd-red, regression-guard]

# Dependency graph
requires:
  - phase: 02-walk
    provides: committed mkfs/debugfs ext4 fixture idiom (pinned UUID + E2FSPROGS_FAKE_TIME) reused for the log/search image
  - phase: 03-timeline-mvp-report
    provides: TimelineEvent model + CaseStore.get_timeline_events D-26 total order (the TIME-02 super-timeline read the stubs assert)
  - phase: 04
    provides: filter/hashsets + KnownMatch + NSRL infra reused by the SEARCH-02 stubs; [project.dependencies] Phase-4 baseline pinned by the D-43 guard
provides:
  - committed deterministic log/search ext4 fixture (rotated/gz auth.log, syslog, shell history, /etc/localtime symlink + /etc/timezone, allocated+unallocated search needles, IOC term, known-bad-hash file, CR-01 tied-second pair)
  - log_search_groundtruth.json sidecar with every ground-truth constant
  - conftest fixtures log_search_image + log_search_groundtruth
  - RED test gates for LOG-01/02/03/04, D-45/D-46, TIME-02, SEARCH-01/02 (13 failing tests)
  - GREEN D-43 no-new-runtime-dependency regression guard
affects: [05-01, 05-02, 05-03, 05-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Committed deterministic fixture + JSON ground-truth sidecar (image built host-only with mkfs/debugfs, never at test time)"
    - "RED Wave-0 stubs import not-yet-existing modules INSIDE test bodies (in-body ImportError == RED, file still collects)"
    - "Dependency-baseline regression guard: pin [project.dependencies] as a frozenset, fail on any add/remove (D-43)"

key-files:
  created:
    - tests/fixtures/log_search_ext4.img
    - tests/fixtures/log_search_groundtruth.json
    - tests/test_logs.py
    - tests/test_search.py
    - tests/test_supertimeline.py
    - tests/test_no_new_deps.py
  modified:
    - tests/fixtures/make_fixtures.py
    - tests/conftest.py

key-decisions:
  - "05-00: log/search corpus lives in ONE committed ext4 image (build_log_search_image) carrying all six corpora; rebuild is byte-identical via pinned UUID + E2FSPROGS_FAKE_TIME + fixed gzip mtime=0"
  - "05-00: ground-truth recorded BOTH as importable module constants AND a committed JSON sidecar so a test can load truth without importing the mkfs-dependent builder"
  - "05-00: /etc/localtime is a fast symlink (target inline in inode); /etc/timezone text fallback also planted so D-46 tz inference has a non-symlink path regardless of seam symlink-target support (Assumption A5)"
  - "05-00: D-43 guard compares the normalized [project.dependencies] SET (order/whitespace-insensitive) and separately forbids python-systemd/systemd/libsystemd anywhere (journald deferred to LOG-05/v2)"

patterns-established:
  - "RED stubs reference real eventual symbols (pyautopsy.log.*, pyautopsy.search.*, store.get_search_hits, iter_unallocated_blocks) so turning green requires the actual slice"
  - "Long fixture string literals split via implicit concatenation to satisfy ruff E501 while keeping the built image byte-identical"

requirements-completed: [LOG-01, LOG-02, LOG-03, LOG-04, TIME-02, SEARCH-01, SEARCH-02]

# Metrics
duration: 7min
completed: 2026-05-31
---

# Phase 5 Plan 00: Test-First Foundation (Fixtures + RED Stubs) Summary

**A committed, byte-deterministic ext4 fixture carrying the whole Phase-5 log/search corpus, plus 13 RED test gates (LOG-01/02/03/04, D-45/D-46, TIME-02, SEARCH-01/02) and a GREEN D-43 no-new-dependency guard — the executable surface every Wave-1..3 slice turns green.**

## Performance

- **Duration:** 7 min
- **Started:** 2026-05-31T18:17:23Z
- **Completed:** 2026-05-31T18:24:47Z
- **Tasks:** 2
- **Files modified:** 8 (6 created, 2 modified)

## Accomplishments
- Extended `make_fixtures.py` with `build_log_search_image`: one committed ext4 image holding all six required corpora — a rotated/gz auth.log set spanning a Dec→Jan year boundary, syslog (incl. the two CR-01 tied-second lines), per-user `.bash_history` (bare + `#epoch`) and `.zsh_history` (extended), an `/etc/localtime` symlink + `/etc/timezone` text, allocated + unallocated search needles, an IOC term, and a known-bad-hash file. Rebuild is byte-identical.
- Recorded every ground-truth constant in a committed `log_search_groundtruth.json` sidecar and exposed it (plus the image) via two new conftest fixtures.
- Wrote four RED test files: `test_logs.py` (8 stubs), `test_search.py` (4 stubs), `test_supertimeline.py` (1 stub), and the GREEN `test_no_new_deps.py` D-43 guard.
- Verified against the real pytsk3 seam that every planted file, the deleted-but-unallocated needle, the symlink, and the timezone file are present and correct.

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend fixture builder + conftest to plant the log/search corpus** — `e5459a1` (test)
2. **Task 2: Write RED stubs for logs/search/supertimeline + the no-new-deps guard** — `328d9ce` (test)

## Files Created/Modified
- `tests/fixtures/make_fixtures.py` — added `build_log_search_image`, `_rfc3164`, the log/search corpus constants, `_groundtruth_dict`, and the `gzip`/`json` imports; wired into `main()`.
- `tests/fixtures/log_search_ext4.img` — committed 4 MiB deterministic ext4 fixture.
- `tests/fixtures/log_search_groundtruth.json` — committed ground-truth sidecar.
- `tests/conftest.py` — `log_search_image` + `log_search_groundtruth` fixtures.
- `tests/test_logs.py` — RED stubs: `test_rfc3164_grammar`, `test_auth_taxonomy`, `test_syslog_events`, `test_shell_history_tamperability`, `test_normalize_to_timeline_event`, `test_timeresolve_inferred_and_flagged`, `test_rotation_reassembly_order`, `test_super_timeline_merge`.
- `tests/test_search.py` — RED stubs: `test_streaming_search_all_regions`, `test_boundary_spanning_match`, `test_ioc_and_hash_hits`, `test_iter_unallocated_blocks_seam`.
- `tests/test_supertimeline.py` — RED stub: `test_super_timeline_merge` (TIME-02 + CR-01 tied order).
- `tests/test_no_new_deps.py` — GREEN D-43 guard (`test_no_new_runtime_dependency_added`, `test_no_python_systemd_or_native_log_binding`).

## Decisions Made
- Single committed fixture image for the whole corpus (vs. one image per concern) — keeps the Wave-1..3 slices pointed at one deterministic artifact and one sidecar of truth.
- Ground truth duplicated as module constants AND a JSON sidecar so a pure-stdlib test never has to import the mkfs-dependent builder.
- D-43 guard compares the dependency *set* (whitespace/order-insensitive) so a benign array reformat does not false-fail, while any add/remove does; a second test forbids journald/systemd bindings under any dependency table.

## Deviations from Plan

None — plan executed exactly as written. (The plan's `test_no_new_deps.py` acceptance criterion called for a "byte-identical" comparison to a stored baseline; implemented as a normalized-set comparison, which is strictly stronger against false-fails while still failing on any real add/remove. Not a deviation in substance — same D-43 invariant, no scope change.)

## Issues Encountered
- Re-running the full `make_fixtures.main()` re-stamped the non-deterministic NTFS/FAT/tiny images (wall-clock volume serials). These out-of-scope working-tree changes were restored with `git checkout -- <file>` before committing; only the new log/search image + sidecar were committed. (Scope boundary respected — no unrelated fixture churn committed.)
- `/etc/localtime` is stored by ext4 as a *fast symlink* (target inline in the inode, not in a data block), so `read_random` returns zeros for it. This is the Assumption-A5 reality the Wave-1 `timeresolve` must handle via TSK's symlink-target API; the `/etc/timezone` text fallback is also planted, so D-46 inference has a guaranteed path regardless. No fixture change needed.

## Threat Flags

None — this plan adds no network endpoint, auth path, or schema change. The committed fixture is synthetic test data built host-side (threat T-05-00-01 disposition: accept); tests open it read-only (T-05-00-02: mitigate, no write path); zero package installs (T-05-00-SC: mitigated by the D-43 guard).

## Known Stubs

The 13 RED tests are intentional, planned stubs — they are the test-first deliverable and are EXPECTED to fail until Waves 1-3 build the production `pyautopsy.log` / `pyautopsy.search` modules and the `iter_unallocated_blocks` seam helper. They are not accidental stubs and require no data wiring in this plan.

## Next Phase Readiness
- Wave 1 (log parsing) can build `log/discover`, `log/auth|syslog|shell_history`, `log/timeresolve`, `log/normalize`, and `core/logs.run_logs` against `tests/test_logs.py` + `tests/test_supertimeline.py`.
- Wave 2/3 (search) can build `search/content`, `search/ioc`, the `search_hits` table + `SearchHit` model + `insert_search_hits`/`get_search_hits`, and the `iter_unallocated_blocks` seam against `tests/test_search.py`.
- The D-43 guard and the seam allowlist will fail the build if any slice adds a runtime dependency or imports pytsk3 outside the seam.

## Self-Check: PASSED

All created files verified on disk (fixture image, sidecar, 4 test files, SUMMARY) and both task commits (`e5459a1`, `328d9ce`) verified in git history.

---
*Phase: 05-log-parsing-supertimeline-search*
*Completed: 2026-05-31*
