---
phase: 05-log-parsing-supertimeline-search
plan: 01
subsystem: log-parsing
tags: [auth-log, rfc3164, rfc5424, rotation, gzip, tz-inference, year-inference, super-timeline, timeline-events, cli, ext-01, d-45, d-46, d-47, time-02, log-01, log-04]

# Dependency graph
requires:
  - phase: 05-00
    provides: committed log/search ext4 fixture + groundtruth sidecar + 13 RED gates (this plan turns the LOG-01/D-45/D-46/LOG-04/TIME-02 subset green)
  - phase: 03-timeline-mvp-report
    provides: TimelineEvent model + CaseStore.get_timeline_events D-26 total order + timeline/builder.explode (the normalize + super-timeline analogs)
  - phase: 04
    provides: core/recover.run_recover orchestrator skeleton (the run_logs analog) + cli recover command pattern
provides:
  - reusable log/ scaffolding (registry/EXT-01, discover/D-45, timeresolve/D-46, normalize/LOG-04) that Wave-2 parsers register into without touching the orchestrator
  - log/auth.py LOG-01 auth.log/secure parser + honest action/outcome taxonomy
  - core/logs.run_logs orchestrator (discover→parse→resolve→normalize→insert_timeline_events) + LogsResult/LogsError
  - pyautopsy logs CLI subcommand
  - evidence/filesystem.read_symlink_target + read_file_bytes seam helpers (pytsk3 stays in seam)
affects: [05-02, 05-03, 05-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "LogParser Protocol + declared-order registry (EXT-01): future parsers register without touching run_logs"
    - "naive-wallclock → flagged-UTC mirror of walk._macb_to_utc_iso for RFC3164 (D-46), with year inference seeded from log mtime + rotation order"
    - "rotated/gz set reassembly oldest→newest (highest index first, gz before non-gz of same index, live file last) for deterministic insert/id tiebreak (CR-01/Pitfall 3)"
    - "run_logs builds the filesystem MACB timeline once (idempotent) so the existing get_timeline_events read IS the merged super-timeline (TIME-02/D-47) — no new ORDER BY"

key-files:
  created:
    - src/pyautopsy/log/__init__.py
    - src/pyautopsy/log/registry.py
    - src/pyautopsy/log/discover.py
    - src/pyautopsy/log/timeresolve.py
    - src/pyautopsy/log/normalize.py
    - src/pyautopsy/log/_grammar.py
    - src/pyautopsy/log/syslog.py
    - src/pyautopsy/log/auth.py
    - src/pyautopsy/core/logs.py
  modified:
    - src/pyautopsy/evidence/filesystem.py
    - src/pyautopsy/cli/main.py

key-decisions:
  - "05-01: shared RFC3164/RFC5424 grammar lives in log/_grammar.py; log/syslog.py exposes only parse_line (the grammar gate Task 1 verify needs) — the full LOG-02 syslog parse() stays Wave 2"
  - "05-01: /etc/localtime is a fast ext4 symlink (read_random yields zeros), so tz inference reads the symlink TARGET via a new evidence/filesystem.read_symlink_target seam helper (meta.link, pytsk3 stays in seam), with /etc/timezone text as the guaranteed fallback (Wave-0 reviewer note / Assumption A5)"
  - "05-01: run_logs builds the filesystem MACB timeline once (only when the source has no timeline events yet) so the Wave-0 super-timeline test — which calls run_walk + run_logs but not build_timeline — gets a populated merged read; idempotent so a prior analyze/build is never double-inserted (D-47, no new ordering code)"
  - "05-01: year inference is a single newest→oldest pass over the ordered records, decrementing the seed year on a backwards month roll; both tz and year are FLAGGED per event (timestamp_source + assumed_timezone + year_inferred/year_basis), UTC fallback warned, never silent (D-46/SOUND-02/CR-01)"

requirements-completed: [LOG-01, LOG-04, TIME-02]

# Metrics
duration: 9min
completed: 2026-05-31
---

# Phase 5 Plan 01: Log Parsing Vertical Slice (auth.log → super-timeline) Summary

**The first end-to-end log capability: `pyautopsy logs <image> --case <dir>` parses auth.log/secure (incl. rotated `.1`/`.2.gz`, reassembled oldest→newest), maps sshd/sudo/PAM lines to honest action/outcome events, time-resolves each line to UTC with inferred-and-flagged tz + year, and merges them into the existing `get_timeline_events` total order — plus the reusable log/ scaffolding (registry/discover/timeresolve/normalize) Wave-2 parsers plug into.**

## Performance

- **Duration:** 9 min
- **Started:** 2026-05-31T18:29:17Z
- **Completed:** 2026-05-31T18:38:55Z
- **Tasks:** 2
- **Files modified:** 11 (9 created, 2 modified)

## Accomplishments

- Stood up the reusable `log/` package: `registry.py` (`LogParser` Protocol + `ParsedRecord` + declared-order registry, EXT-01), `discover.py` (rotated/gz set reassembly oldest→newest + completeness finding, D-45), `timeresolve.py` (D-46 tz/year inference mirroring `walk._macb_to_utc_iso`, honest per-event flagging), `normalize.py` (parsed-record → `TimelineEvent`, mirroring `builder._explode`, LOG-04), and the shared `_grammar.py` RFC3164/RFC5424 line grammar.
- Built `log/auth.py` (LOG-01): the auth.log/secure parser with a small honest action/outcome taxonomy (ssh-login success/failure, session opened/closed, sudo granted/denied, account created); unmatched lines still become events carrying their raw message; self-registers in the EXT-01 registry at import time.
- Built `core/logs.py::run_logs`: the orchestrator mirroring `run_recover` — double `assert_source_not_mounted`, volume loop with D-20 encrypted-skip, host-tz resolution per volume, discover→parse(registry)→resolve→normalize, a single `store.transaction(): insert_timeline_events()` (sole writer), the two-arm expected/crashed audit, and a counts-only `LogsResult` (no wall-clock).
- Added the `pyautopsy logs` CLI subcommand mirroring `recover` (error-set→exit-code mapping, explicit `sqlite3.Error` catch per BL-02, deterministic echo). Verified end-to-end on the fixture: 1 log set, 9 auth events, exit 0.
- Added `evidence/filesystem.read_symlink_target` + `read_file_bytes` seam helpers so tz inference reads `/etc/localtime`'s target and `/etc/timezone` text while pytsk3 stays inside the seam (D-14).

## Task Commits

1. **Task 1: log/ scaffolding — registry, discover, timeresolve, normalize (+seam helpers)** — `7bfb68a` (feat)
2. **Task 2: auth.py parser + core/logs.py orchestrator + `pyautopsy logs` CLI** — `9f7882d` (feat)

## Files Created/Modified

- `src/pyautopsy/log/__init__.py` — package init + public exports.
- `src/pyautopsy/log/registry.py` — `LogParser` Protocol, `ParsedRecord` dataclass, declared-order registry (`register`/`iter_parsers`/`clear_registry`).
- `src/pyautopsy/log/discover.py` — `discover_log_sets`/`order_rotated_set`/`decode_member`, `LogMember`/`LogSet`/`CompletenessFinding` (D-45).
- `src/pyautopsy/log/timeresolve.py` — `resolve_host_tz`/`to_utc`/`zone`/`rfc3164_components`/`infer_years`/`naive_from_components` + `TIMESTAMP_SOURCE_BY_LABEL` (D-46).
- `src/pyautopsy/log/normalize.py` — `to_event` parsed-record → `TimelineEvent` (LOG-04).
- `src/pyautopsy/log/_grammar.py` — shared RFC3164/RFC5424 grammar + `SyslogLine`/`parse_line`.
- `src/pyautopsy/log/syslog.py` — re-exports `parse_line` (Wave-1 grammar gate; full LOG-02 `parse` is Wave 2).
- `src/pyautopsy/log/auth.py` — `AuthParser`/`AUTH_PATTERNS`/`parse` (LOG-01), self-registers.
- `src/pyautopsy/core/logs.py` — `run_logs`/`LogsResult`/`LogsError`/`_EXPECTED_LOGS_ERRORS`/`_latest_evidence_source_id`.
- `src/pyautopsy/evidence/filesystem.py` — added `read_symlink_target` + `read_file_bytes` seam helpers.
- `src/pyautopsy/cli/main.py` — added the `logs` Typer command + `run_logs`/`LogsError` import.

## Decisions Made

See the `key-decisions` frontmatter. The two load-bearing ones: (1) `run_logs` idempotently builds the filesystem MACB timeline so the Wave-0 super-timeline test (which does not call `build_timeline`) sees a merged read — keeping TIME-02 as the existing `get_timeline_events` order with no new sorting; (2) tz inference reads the `/etc/localtime` symlink target via a new seam helper because the ext4 fast symlink reads as zeros through `read_random`, with `/etc/timezone` text as the guaranteed fallback.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2/3 - Missing critical functionality] run_logs builds the filesystem timeline so the super-timeline merge is non-empty**
- **Found during:** Task 2 (the two `test_super_timeline_merge` gates failed with "missing filesystem events").
- **Issue:** The Wave-0 tests call `run_ingest` → `run_walk` → `run_logs` then read `get_timeline_events`, expecting BOTH filesystem and log events. In the existing codebase `run_walk` only inventories `files`; filesystem *timeline* events are produced by `build_timeline` (invoked by `run_analyze`, not `run_walk`). With neither `build_timeline` nor `analyze` in the test, the merged read had only log events.
- **Fix:** `run_logs` now builds the filesystem MACB timeline (via `timeline.builder.explode` over `get_files`) inside its single transaction, **only when the source has no timeline events yet** (idempotent — a prior `analyze`/`build_timeline` is never double-inserted). This makes `run_logs` the TIME-02 super-timeline assembler the tests require, adds no new ORDER BY (the store's D-26 read is still the single ordering source), and respects WR-01 (one transaction, sole writer).
- **Files modified:** `src/pyautopsy/core/logs.py`
- **Commit:** `9f7882d`

**2. [Rule 3 - Blocking issue] read_symlink_target / read_file_bytes seam helpers added**
- **Found during:** Task 1 (tz inference needs the `/etc/localtime` target, which `read_random` returns as zeros for an ext4 fast symlink — the Wave-0 reviewer note).
- **Issue:** `log/` must not import pytsk3 (D-14), but the symlink target is only available via the native `meta.link` field.
- **Fix:** Added `read_symlink_target(fs, path)` and a bounded `read_file_bytes(fs, path)` to `evidence/filesystem.py` (an allowlisted seam), exposing decoded strings/bytes without leaking native objects; `run_logs` passes these to `timeresolve.resolve_host_tz` as callbacks. The seam-allowlist test stays green.
- **Files modified:** `src/pyautopsy/evidence/filesystem.py`, `src/pyautopsy/core/logs.py`
- **Commit:** `7bfb68a` (seam) / `9f7882d` (wiring)

## Authentication Gates

None.

## Verification

- `python -m pytest tests/test_logs.py -k "rfc3164 or auth_taxonomy or normalize or timeresolve or rotation or super_timeline" tests/test_supertimeline.py -q` → **7 passed** (all Wave-1 log gates).
- `python -m pytest tests/test_seam_allowlist.py tests/test_readonly_guarantee.py tests/test_no_new_deps.py tests/test_cli_smoke.py -q` → green.
- `ruff check src/pyautopsy` → no issues; `mypy src/pyautopsy/log src/pyautopsy/core/logs.py` → no issues.
- Full suite: **197 passed, 6 failed** — the 6 failures are the explicitly out-of-scope Wave-2/3 RED stubs (`test_syslog_events`, `test_shell_history_tamperability`, `test_streaming_search_all_regions`, `test_boundary_spanning_match`, `test_ioc_and_hash_hits`, `test_iter_unallocated_blocks_seam`). No in-scope regression.
- CLI smoke: `pyautopsy logs <fixture> --case <tmp>` → "logs complete … log sets: 1, events parsed: 9, auth events: 9", exit 0.

## Known Stubs

- `log/syslog.py` exposes only `parse_line` (the shared grammar). The full LOG-02 `syslog.parse(...)` service/kernel/cron taxonomy and `log/shell_history.py` (LOG-03) are **intentionally deferred to Wave 2** — the plan scoped this slice to the auth vertical only. Their RED gates (`test_syslog_events`, `test_shell_history_tamperability`) remain failing by design and are resolved by 05-02. This is a planned, documented stub, not an accidental one.

## Threat Flags

None — no new network endpoint, no auth path, no schema change (D-47: `timeline_events` untouched; log events use the existing table). Evidence bytes/filenames are decoded `utf-8`/`errors="replace"` as DATA only (T-05-01-01); the source is re-asserted not-mounted before+after open and read through the read-only seams (T-05-01-02, covered by `test_readonly_guarantee.py`); inferred tz/year are flagged per event, never asserted as fact (T-05-01-03); gz members are inflated through stdlib `gzip` over a bounded in-memory buffer (T-05-01-04); zero package installs (T-05-01-SC, `test_no_new_deps.py` green). The two new seam helpers (`read_symlink_target`, `read_file_bytes`) are read-only and bounded, inside the existing D-14 allowlist.

## Self-Check: PASSED

All created files verified on disk and both task commits (`7bfb68a`, `9f7882d`) verified in git history (see below).
