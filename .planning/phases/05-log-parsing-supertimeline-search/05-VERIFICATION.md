---
phase: 05-log-parsing-supertimeline-search
verified: 2026-05-31T00:00:00Z
status: passed
score: 14/14 must-haves verified
overrides_applied: 0
mode: mvp
re_verification: false
open_warnings:  # From 05-REVIEW.md — deferred by user, judged NOT goal-blocking
  - id: WR-01
    summary: "run_search ioc_terms param reachable only from tests; --ioc file path works"
    blocking: false
  - id: WR-02
    summary: "Hash-arm (0,0)/path=None SearchHit fallback when file row missing — unreachable in practice (match_bad_hashes only emits for present rows); deterministic"
    blocking: false
  - id: WR-03
    summary: "run_logs/run_search run read-only raw SELECT inline (boundary nit, not a soundness/determinism hazard)"
    blocking: false
  - id: WR-04
    summary: "Pre-open assert_source_not_mounted fires before audit log built — mounted-source rejection clean+correct but unlogged; read-only protection still holds"
    blocking: false
  - id: WR-05
    summary: "RFC3164 grammar requires host token; hostless/relay lines fall to unmatched bucket — coverage gap, degrades gracefully"
    blocking: false
  - id: WR-06
    summary: "dateext negative-index ordering/completeness bug — affects dateext rotation only; numeric rotation correct"
    blocking: false
  - id: WR-07
    summary: "D-45 completeness finding computed but not threaded into report (honesty disclosure gap)"
    blocking: false
  - id: IN-01..IN-04
    summary: "Cosmetic/comment/magic-string items"
    blocking: false
---

# Phase 5: Log Parsing, Super-Timeline & Search Verification Report

**Phase Goal:** An examiner sees filesystem and log evidence merged into one UTC-ordered super-timeline and can search across allocated, unallocated, and file content — completing the full "image + logs → defensible report" pipeline.
**Verified:** 2026-05-31
**Status:** passed
**Re-verification:** No — initial verification (no prior VERIFICATION.md)
**Mode:** mvp

## Summary

All 7 phase requirements (LOG-01..04, TIME-02, SEARCH-01, SEARCH-02) are achieved
in the actual codebase, not merely in SUMMARY claims. The three Critical defects a
prior deep review found (CR-01/02/03) — which a green test suite had masked — are
independently confirmed FIXED on the **real orchestrated path**, not just in unit
tests. The core invariants hold: single native seam (D-14), CaseStore sole writer,
read-only forensic soundness, no new runtime dependency (D-43), and CLI-02
determinism (no wall-clock leak). Full suite: **211 passed**.

## Goal Achievement

### Observable Truths (merged ROADMAP success criteria + PLAN must_haves)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `pyautopsy logs <image> --case <dir>` surfaces auth.log/secure login/SSH/sudo/failed-auth events | ✓ VERIFIED | `log/auth.py:36-48` taxonomy (Accepted=ssh-login, Failed password=failure, sudo granted/denied, session opened/closed); CLI `logs` cmd `cli/main.py:346`→`run_logs`; test_logs.py orchestrated test asserts `by_source["auth"]` |
| 2 | Rotated/compressed auth sets reassembled oldest→newest | ✓ VERIFIED | `discover.order_rotated_set` (order_key `(-index, gz)`), `decode_member` gzip inflate; gz fixture in make_fixtures |
| 3 | RFC3164 → UTC via image tz (/etc/localtime→/etc/timezone), tz AND year flagged per event; undeterminable tz → UTC+warning | ✓ VERIFIED | `timeresolve.resolve_host_tz` + `to_utc` emits `timestamp_source`/`assumed_timezone`/`time_warning`; `infer_years` emits `year_inferred`/`year_basis` |
| 4 | syslog/messages (service/kernel/cron/error) parsed into timeline | ✓ VERIFIED | `log/syslog.py` name="syslog", matches syslog/messages; **orchestrated** `iter_parsers()` yields syslog (confirmed in fresh process); test asserts `by_source["syslog"]` non-empty via run_logs |
| 5 | Per-user .bash_history/.zsh_history parsed; epoch used when present else flagged no-timestamp + tamperability finding | ✓ VERIFIED | `log/shell_history.py` no-ts basis flag + D-44 tamperability finding; `discover_shell_histories` per-user sets; test asserts `actor=="user=alice"` |
| 6 | Both Wave-2 parsers register into shared registry + flow through unchanged run_logs (EXT-01) | ✓ VERIFIED | `log/__init__.py:33-37` imports auth+shell_history+syslog for registration side-effect; `core/logs.py:54` imports package; `_parse_log_set` uses `iter_parsers()` |
| 7 | All log events normalized into shared TimelineEvent model identical to filesystem events (LOG-04) | ✓ VERIFIED | `log/normalize.to_event` → TimelineEvent rows; written via `insert_timeline_events` into same `timeline_events` table |
| 8 | Super-timeline merges fs + log events into one UTC-sorted view (TIME-02) | ✓ VERIFIED | `core/logs.py:382-390` builds fs MACB events + log events into one table; `assemble.py:311` reads `get_timeline_events` with **no new ORDER BY** (comment 421-422); test_supertimeline asserts interleaved + sorted |
| 9 | `pyautopsy search --term` gives hits with file+offset across allocated content + unallocated + metadata | ✓ VERIFIED | `core/search.py` content arm via `search_image` (allocated+unallocated), hash arm metadata region; CLI `search` cmd `cli/main.py:582` |
| 10 | Boundary-spanning match found exactly once with correct absolute offset | ✓ VERIFIED | search/content streaming overlap logic; test_search.py boundary test passes |
| 11 | IOC lists + known-bad-hash sets match (reusing Phase-4 filter infra), report by file+offset | ✓ VERIFIED | `search/ioc.py` reuses filter/hashsets `match_bad_hashes`; hash hits emitted as term_kind="hash" SearchHit + neutral KnownMatch |
| 12 | All reads through two existing seams read-only; unallocated via new iter_unallocated_blocks; search/ imports no pytsk3 | ✓ VERIFIED | `filesystem.py:582 iter_unallocated_blocks`; D-14 grep: only recover/walk/filesystem/image import pytsk3 (walk/recover are docstring-only); test_seam_allowlist 4 passed |
| 13 | `analyze --logs --search <term>` → ONE report with merged super-timeline + log-findings + search-results sections | ✓ VERIFIED | `analyze.py:347 if logs: run_logs`, `:358 if search_requested: run_search`; `assemble.py` log_findings (455) + search_results (491) sections |
| 14 | Default `analyze` byte-identical to Phase-4 baseline (CLI-02, D-48); two --logs runs byte-identical incl tied events (CR-01) | ✓ VERIFIED | test_reproducibility: test_default_analyze_unchanged, test_two_analyze_runs_byte_identical_report, test_tied_log_events_stable, test_tied_log_events_null_meta_tiebreak all pass; no wall-clock in logs.py (confirmed) |

**Score:** 14/14 truths verified

## Critical-Fix Confirmation (independent, on the orchestrated path)

| CR | Was | Fix Verified | Evidence (codebase, not SUMMARY) |
|----|-----|--------------|----------------------------------|
| CR-01 | syslog+shell-history dead on real CLI path (only auth imported/discovered) | ✓ HOLDS | Fresh-process import of ONLY `pyautopsy.core.logs` → `iter_parsers()` yields `['auth','shell-history','syslog']`. `__init__.py:33-37` registers all three; `discover.DEFAULT_LOG_BASENAMES` adds syslog/messages; `discover_shell_histories` finds .bash_history/.zsh_history; orchestrator calls BOTH discover fns (`logs.py:350-353`). Regression test `test_run_logs_orchestrated_emits_syslog_and_shell_history` genuinely drives `run_logs` (does NOT hand-import parser modules) and asserts syslog+shell-history events in the merged timeline — would fail on regression. |
| CR-02 | `datetime.now()` wall-clock year seed leaks into persisted ts_utc → CLI-02 break | ✓ HOLDS | `inspect.getsource(logs)` contains NO `datetime.now`. `_seed_year_from_mtime` chain is member mtime → newest mtime in set → epoch year 1970 (flagged) — every branch evidence-derived/deterministic. |
| CR-03 | month-only RFC3164 year inference + single-line cascade mis-dates timeline | ✓ HOLDS | `infer_years` compares `(month,day)` tuples (timeresolve.py:213-231); cascade guard requires next-older record also in H2 (`confirmed`, line 224) so a lone out-of-order line is absorbed. Verified live: `[(12,20),(1,5)] seed 2026 → [2025,2026]`; `[(1,2),(1,20)] → [2026,2026]`. Tests test_infer_years_same_month_year_boundary + _single_out_of_order_no_cascade present and passing. |

## Open Warnings (deferred by user) — judged against invariants

| Warning | Defeats a requirement / core invariant? | Verdict |
|---------|------------------------------------------|---------|
| WR-02 `(0,0)`/path=None hash-hit fallback | No. `match_bad_hashes` only emits matches for rows present in `files`, so the `fr is None` branch is unreachable; the lookup is deterministic. NOT a CLI-02 non-determinism. | Not blocking |
| WR-04 pre-open mount guard fires pre-audit | No. The guard still **rejects** the mounted source (read-only/forensic soundness preserved); only the FAIL audit record is skipped on that narrow path, and the CLI maps MountedSourceError to a clean exit. An audit-completeness gap, not a soundness or requirement failure. | Not blocking |
| WR-01/03/05/06/07, IN-01..04 | Coverage/boundary/cosmetic items; none defeats LOG/TIME/SEARCH requirements or D-14/sole-writer/CLI-02. WR-07 (completeness finding not surfaced) weakens D-45 honesty disclosure but does not defeat the LOG-01/02 parse requirements. | Not blocking |

## Core Invariant Checks

| Invariant | Status | Evidence |
|-----------|--------|----------|
| D-14 single native seam | ✓ | Only recover/walk/filesystem/image import pytsk3; walk+recover matches are docstring-only (no real import); test_seam_allowlist passes |
| CaseStore sole writer | ✓ | run_logs/run_search persist via single `store.transaction()` + insert_*; no other DB write path |
| Read-only forensic soundness | ✓ | assert_source_not_mounted before+after open in both orchestrators; image opened read-only via image seam |
| CLI-02 determinism | ✓ | No datetime.now in logs.py; reproducibility tests byte-identical pass |
| D-43 no new runtime dep | ✓ | test_no_new_deps passes |

## Requirements Coverage

| Requirement | Source Plan | Status | Evidence |
|-------------|-------------|--------|----------|
| LOG-01 (auth) | 05-01, 05-04 | ✓ SATISFIED | auth.py taxonomy + run_logs + logs CLI |
| LOG-02 (syslog/messages) | 05-02, 05-04 | ✓ SATISFIED | syslog.py registered + orchestrated emit confirmed (CR-01 fix) |
| LOG-03 (shell history) | 05-02, 05-04 | ✓ SATISFIED | shell_history.py + discover_shell_histories + tamperability finding |
| LOG-04 (shared event model) | 05-01, 05-04 | ✓ SATISFIED | normalize.to_event → TimelineEvent into shared table |
| TIME-02 (super-timeline) | 05-01, 05-04 | ✓ SATISFIED | get_timeline_events merged read, no new ORDER BY; test_supertimeline |
| SEARCH-01 (literal/regex across allocated/unalloc/content) | 05-03, 05-04 | ✓ SATISFIED | search/content + iter_unallocated_blocks seam |
| SEARCH-02 (IOC + known-bad-hash) | 05-03, 05-04 | ✓ SATISFIED | search/ioc reuses filter/hashsets |

No orphaned requirements: REQUIREMENTS.md maps exactly LOG-01..04, TIME-02, SEARCH-01/02 to Phase 5; all 7 are claimed by plans and verified.

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Orchestrated registry has all 3 parsers | `import pyautopsy.core.logs; iter_parsers()` | `['auth','shell-history','syslog']` | ✓ PASS |
| No wall-clock in logs.py | `inspect.getsource` grep `datetime.now` | absent | ✓ PASS |
| CR-03 same-month boundary | `infer_years([(12,20..),(1,5..)], 2026)` | `[2025,2026]` | ✓ PASS |
| CR-03 same-month same-year | `infer_years([(1,2..),(1,20..)], 2026)` | `[2026,2026]` | ✓ PASS |
| CLI exposes logs+search | `get_command(app).commands` | analyze,ingest,logs,recover,search,walk | ✓ PASS |
| Full suite | `PYTHONPATH=src python -m pytest -q` | 211 passed | ✓ PASS |
| Seam allowlist + no-new-deps gates | pytest test_seam_allowlist test_no_new_deps | 4 passed | ✓ PASS |

## Anti-Patterns Found

None goal-blocking. No unreferenced TBD/FIXME/XXX debt markers in Phase-5 modified files. Stub-pattern matches in the parsers are deliberate `None`-flagged-not-dropped designs (records always emitted), not hollow returns.

## Human Verification Required

None. All success criteria are programmatically verifiable from the committed
fixture image and the test suite; there is no visual/UX/external-service surface
in this phase (CLI + report-body bytes only, all asserted by tests).

## Gaps Summary

No gaps. The phase goal is achieved: the merged UTC super-timeline (fs + auth +
syslog + shell-history) and the literal/regex/IOC/known-bad-hash search are wired
end-to-end through the orchestrated CLI path, default analyze stays byte-identical
to the Phase-4 baseline, and all three previously-masked Critical defects are
independently confirmed fixed on the real `run_logs` path. The 7 open review
warnings are non-blocking quality/disclosure items deferred by the user; none
defeats a Phase-5 requirement or a core invariant (D-14, sole-writer, read-only,
CLI-02).

---

_Verified: 2026-05-31_
_Verifier: Claude (gsd-verifier)_
