---
phase: 01-forensic-foundation
plan: 03
subsystem: util
tags: [safe-extract, security-gate, tarfile, zipfile, zip-slip, decompression-bomb, ingest-04, d-11]

# Dependency graph
requires:
  - "01-00: tests/fixtures/make_fixtures.py malicious-archive builders + conftest per-archive fixtures (zip-slip, symlink-escape, device-file, ratio-bomb, count-bomb)"
provides:
  - "safe_extract(archive_path, dest, limits=None, *, on_member_error) — the only sanctioned archive expander (D-11); confines members, refuses symlink/special, caps decompression bombs"
  - "ExtractionLimits frozen dataclass — configurable bomb caps (total/entry size, ratio, count, depth) with documented sane defaults"
  - "ExtractionRejected exception — every guard breach is translated to this with a specific reason; the jail never crashes with a raw tarfile/zipfile traceback"
  - "ExtractionResult / MemberRecord — per-member outcome metadata (original name preserved as evidence, sanitized on-disk name, rejection reason)"
  - "Phase-1 security completion gate: parametrized malicious-fixture suite proving every hostile input is REJECTED with zero jail escape"
affects: [05-archive-parsers, 05-log-parsers]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "single sanctioned archive expander (D-11) — no callers in Phase 1; consumers arrive Phase 5"
    - "explicit filter='data' (tarfile.data_filter) per tar member, never the version default (Pitfall 3)"
    - "confinement runs on the ORIGINAL stored member name (rejects absolute/.. rather than silently relativizing, which masks a tampering signal)"
    - "hand-written zip confinement + external-attr symlink-mode refusal (zipfile has no filter — Pitfall 2)"
    - "running uncompressed-byte counter aborts a total-size bomb mid-stream before disk exhaustion (Pitfall 1)"
    - "per-member error isolation: on_member_error='skip' records a rejection and continues"
    - "on-disk name sanitized; original member name preserved as evidence metadata (V5)"

key-files:
  created:
    - src/pyautopsy/util/safe_extract.py
    - tests/test_safe_extract.py
  modified: []

key-decisions:
  - "Confinement is enforced on the ORIGINAL stored name BEFORE the stdlib data filter: data_filter would rewrite /etc/x -> etc/x, silently relativizing an absolute escape; we REJECT it instead because the absolute name is a tampering signal (forensic soundness)."
  - "Used the public tarfile.data_filter callable per member (not the private _get_filter_function) to apply filter='data' as defense-in-depth, while our own realpath confinement + bomb caps are the primary controls; a member whose name is rewritten by the filter is treated as an escape attempt and rejected."
  - "Tar bomb caps are enforced by a streamed running byte counter (1 MiB chunks) so a total-size bomb aborts mid-write; zip ratio is checked pre-extract via ZipInfo.file_size/compress_size, then re-verified by the same streamed counter."
  - "Default-raise on the first rejected member (on_member_error='raise') so a single hostile input is loud; on_member_error='skip' gives per-member isolation when a caller wants benign siblings to still extract."

requirements-completed: [INGEST-04]

# Metrics
duration: 4min
completed: 2026-05-30
---

# Phase 1 Plan 03: Hardened safe_extract Jail Summary

**Built `util/safe_extract.py` — the single sanctioned archive expander (INGEST-04, D-11) — with realpath path-confinement, symlink/hardlink/device/special refusal for both tar and zip, explicit `filter='data'` per tar member, hand-written zip confinement, and decompression-bomb caps (total/per-entry size, ratio, count, depth) whose running byte counter aborts a bomb mid-stream; the parametrized malicious-fixture gate proves every hostile input (zip-slip, symlink-escape, device-file, ratio/size-bomb, count-bomb) is REJECTED with zero jail escape. `pytest -q` is green (85 passed, 1 xfailed — the ingest smoke stays xfail until 01-04).**

## Performance

- **Duration:** ~4 min
- **Completed:** 2026-05-30T16:48Z
- **Tasks:** 2 completed (TDD: RED then GREEN)
- **Files:** 2 created

## Accomplishments
- `safe_extract(archive_path, dest, limits=None, *, on_member_error)` — confines every member to `realpath(dest)`, rejects absolute paths and `..` traversal on the original stored name, refuses symlinks/hardlinks/device/special files (tar via explicit `tarfile.data_filter` + up-front type checks; zip via external-attr symlink-mode bits), and enforces hard bomb caps.
- `ExtractionLimits` frozen dataclass with documented sane defaults (1 GiB total / 256 MiB per-entry / 100× ratio / 10 000 entries / depth 3), all overridable per call.
- `ExtractionRejected` translates every guard breach into a specific reason (the jail never surfaces a raw tarfile/zipfile traceback); `ExtractionResult`/`MemberRecord` carry per-member outcomes with the original member name kept as evidence and a sanitized on-disk name.
- Parametrized `test_malicious_fixture_gate` over all six hostile fixtures is the Phase-1 security completion gate (D-11 / 01-VALIDATION.md): each raises `ExtractionRejected` and nothing escapes `tmp_path`.
- Full suite green and lint/type clean: `pytest` → 85 passed / 1 xfailed; `ruff check src tests` clean; `mypy src` clean. Both plan grep gates pass (`filter='data'`, `realpath`).

## Task Commits

1. **Task 1 + 2 (RED):** failing safe_extract jail tests — `825acf5` (test)
2. **Task 1 + 2 (GREEN):** hardened safe_extract jail implementation — `3a72030` (feat)

The two TDD tasks share one test file (it covers both confinement and bomb caps); RED was committed once with the full failing suite, GREEN once with the complete implementation, rather than splitting Task 1/Task 2 across separate commits.

## Files Created/Modified
- `src/pyautopsy/util/safe_extract.py` — the jail: `safe_extract`, `ExtractionLimits`, `ExtractionRejected`, `ExtractionResult`, `MemberRecord`; tar + zip paths with confinement, special-file refusal, bomb caps, name sanitization, per-member isolation.
- `tests/test_safe_extract.py` — 23 tests: traversal (tar+zip), symlink (tar+zip), device, absolute path, benign extract (tar+zip), name-preservation, per-member isolation, total/per-entry/ratio/count caps, streamed-abort, limits defaults/overridability, and the 6-case malicious-fixture gate.

## Decisions Made
- **Confine on the original name, before the stdlib filter.** `tarfile.data_filter` silently relativizes `/etc/cron.d/x` → `etc/cron.d/x`. For evidence that rewrite hides a tampering signal, so `safe_extract` runs `realpath` confinement on the raw stored name first and REJECTS absolute/`..` members; it additionally rejects any member whose name the data filter would rewrite (escape attempt).
- **`filter='data'` as defense-in-depth, our caps as primary.** The public `tarfile.data_filter` is applied per tar member (explicit, never the version default — Pitfall 3), but the realpath confinement and the hand-written bomb caps are the load-bearing controls (`filter='data'` does NOT stop bombs — Pitfall 1).
- **Streamed running byte counter.** Tar members are streamed in 1 MiB chunks with a running total so a total-size bomb aborts mid-write (verified: < the full bomb lands on disk); zip ratio is checked via `ZipInfo.file_size/compress_size` before extract and re-verified by the same counter.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Bug] Absolute-path tar member was not rejected by `filter='data'` alone**
- **Found during:** Task 1 (running the RED suite → GREEN).
- **Issue:** `test_absolute_path_tar_rejected` did not raise. `tarfile.data_filter` *relativizes* an absolute member (`/etc/cron.d/x` → `etc/cron.d/x`) rather than rejecting it, so applying the filter first and confining the rewritten name let the member through (silently, into the jail).
- **Fix:** Run `realpath` confinement on the ORIGINAL stored name *before* the data filter (rejecting absolute names and `..` outright), and treat any data-filter name rewrite as an escape attempt. An absolute member name is a tampering signal that must be REJECTED, not normalized.
- **Files modified:** `src/pyautopsy/util/safe_extract.py`.
- **Commit:** `3a72030`.

**Total deviations:** 1 auto-fixed (Rule 1). No scope creep; no new dependencies.

## TDD Gate Compliance
Config `tdd_mode` is false, so plan-level RED→GREEN gate commits were not enforced, but the plan tasks are `tdd="true"` and were executed RED→GREEN: the failing test suite (`825acf5`, `test(...)`) was confirmed to fail for the right reason (`ModuleNotFoundError: pyautopsy.util.safe_extract`) before the implementation (`3a72030`, `feat(...)`) made it green. No REFACTOR commit was needed.

## Known Stubs
None. `safe_extract` is fully implemented and tested. It has no caller in the Phase-1 ingest path by design (D-11 / 01-RESEARCH.md §Architecture note) — its consumers (archive/log parsers) arrive in Phase 5. This is an intentional, documented standalone-gate utility, not a stub.

## Threat Flags
None. The implementation introduces no security surface beyond the plan's `<threat_model>`; it is a defensive control that mitigates T-1-04 / T-1-04-A/B/C/D and writes only inside the caller-supplied destination jail.

## Verification Evidence
- `pytest -q tests/test_safe_extract.py` → 23 passed (every malicious fixture REJECTED; benign tar/zip extract into the jail only).
- `pytest -q` (full suite) → 85 passed, 1 xfailed (the deliberately-xfail `test_ingest_smoke`, Walking Skeleton target for 01-04 — stays xfail as required).
- `ruff check src tests` → All checks passed.
- `mypy src` → Success: no issues found in 12 source files.
- Grep gates: `grep -q "filter=['\"]data['\"]"` → PASS; `grep -q realpath` → PASS.
- Streamed-abort: total-size-bomb test confirms < the full 8-entry bomb is written to disk before `ExtractionRejected`.

## Self-Check: PASSED
Both created files exist on disk (`src/pyautopsy/util/safe_extract.py`, `tests/test_safe_extract.py`) and both task commits (`825acf5`, `3a72030`) are present in git history.
