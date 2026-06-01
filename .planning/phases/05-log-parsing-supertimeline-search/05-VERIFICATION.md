---
phase: 05-log-parsing-supertimeline-search
verified: 2026-06-01T00:00:00Z
status: passed
score: 16/16 must-haves verified
overrides_applied: 0
mode: mvp
re_verification:
  previous_status: passed
  previous_score: 14/14
  context: "Gap-closure re-verification after `--gaps-only` execution (plans 05-05, 05-06) closing HUMAN-UAT gaps G-2 (MAJOR/failed) and G-1 (minor/advisory)."
  gaps_closed:
    - "G-2: D-44 shell-history tamperability + D-45 log-completeness findings now surfaced in report.json/report.html (was 0 occurrences of 'tamper')."
    - "G-1: D-46 year inference reconciled to the committed fixture's mtime anchor (2023/2022); sidecar + constants + guard test now agree; image not rebuilt."
  gaps_remaining: []
  regressions: []
open_warnings:  # Carried forward from 05-VERIFICATION base phase (deferred by user, judged NOT goal-blocking) + 05-REVIEW-gaps gap-closure review (0 critical, 4 warning, 5 info)
  - id: WR-01
    summary: "run_search ioc_terms param reachable only from tests; --ioc file path works"
    blocking: false
  - id: WR-02
    summary: "Hash-arm (0,0)/path=None SearchHit fallback when file row missing — unreachable in practice; deterministic"
    blocking: false
  - id: WR-03
    summary: "run_logs/run_search run read-only raw SELECT inline (boundary nit)"
    blocking: false
  - id: WR-04
    summary: "Pre-open assert_source_not_mounted fires before audit log built — rejection clean+correct but unlogged; read-only protection holds"
    blocking: false
  - id: WR-05
    summary: "RFC3164 grammar requires host token; hostless/relay lines fall to unmatched bucket — degrades gracefully"
    blocking: false
  - id: WR-06
    summary: "dateext negative-index ordering/completeness bug — affects dateext rotation only; numeric rotation correct"
    blocking: false
  - id: WR-07
    summary: "RESOLVED by 05-05 — D-45 completeness finding now threaded into report (was the honesty disclosure gap)."
    blocking: false
  - id: GR-WR-01
    summary: "05-REVIEW-gaps WR-01: _seed_year_from_mtime uses getattr(row,'mtime',0) swallowing default — robustness nit, works on current typed seam row"
    blocking: false
  - id: GR-WR-02
    summary: "05-REVIEW-gaps WR-02: completeness LogFinding emitted per single-member shell-history set produces low-signal boilerplate disclosures"
    blocking: false
  - id: GR-WR-03
    summary: "05-REVIEW-gaps WR-03: findings_for re-parses history file a second time (harmless today — tamperability is a constant string)"
    blocking: false
  - id: GR-WR-04
    summary: "05-REVIEW-gaps WR-04: findings_count is len(sets)+len(histories), not a count of substantive anomalies — framing/over-claim nit"
    blocking: false
  - id: IN-01..IN-05
    summary: "Cosmetic/comment/validation/derive-from-anchor items from base + gap-closure review"
    blocking: false
---

# Phase 5: Log Parsing, Super-Timeline & Search Verification Report

**Phase Goal:** An examiner sees filesystem and log evidence merged into one UTC-ordered super-timeline and can search across allocated, unallocated, and file content — completing the full "image + logs → defensible report" pipeline.
**Verified:** 2026-06-01 (gap-closure re-verification); base phase 2026-05-31
**Status:** passed
**Re-verification:** Yes — after gap closure (G-2 MAJOR + G-1 minor) via plans 05-05 / 05-06. The base-phase verification below is preserved; the gap-closure section is additive.
**Mode:** mvp

## Re-Verification Summary (Gap Closure 05-05 + 05-06)

The base phase was already `status: passed` (14/14). HUMAN-UAT then surfaced two
gaps, both now **independently confirmed closed against the actual codebase**, not
merely claimed in SUMMARY:

| Gap | Was | Now | Codebase Evidence (verified live) |
|-----|-----|-----|-----------------------------------|
| **G-2** (MAJOR, failed UAT test 9): D-44 tamperability + D-45 completeness findings COMPUTED but DROPPED before the report (0 occurrences of "tamper" in report.json/html). | ✗ failed | ✓ **CLOSED** | (1) Additive `log_findings` table/model/writer: `case/schema.sql:138 CREATE TABLE IF NOT EXISTS log_findings`, `case/models.py:257 class LogFinding`, `store.py:631 insert_log_findings` + `:651 get_log_findings` (parameterized SELECT, store-owned `ORDER BY id`, D-41). (2) `core/logs.py` threads BOTH: D-45 `completeness` per LogSet (`:438-450`), D-44 `tamperability` per shell-history member (`_parse_log_set` `:595-605`), persisted via `store.insert_log_findings(all_findings)` (`:500`) INSIDE the single `with store.transaction()` (`:493`). (3) `assemble.py:480-493` builds `log_findings["disclosures"]` from `get_log_findings` rows in store id order; `report.html.j2` renders them. **Live e2e:** `analyze --logs --search` → report.json `tamper`=1, report.html `tamper`=4; 6 disclosures, categories `['completeness','tamperability']`. |
| **G-1** (minor/advisory): D-46 mtime-anchored year inference yielded 2023/2022 while sidecar documented 2026/2025. | ◐ noted | ✓ **CLOSED** | Path B (no rebuild). `make_fixtures.py:762 LOG_SEARCH_YEAR = 2023`, `:763 LOG_SEARCH_PREV_YEAR = LOG_SEARCH_YEAR - 1`; sidecar `log_search_groundtruth.json` year=2023/prev_year=2022. **Computed live:** `datetime.fromtimestamp(1700000000, utc)` → `2023-11-14T22:13:20+00:00`, year 2023 / prev 2022 — internally consistent. Image sha256 `6e41afad…079b0` **UNCHANGED** before+after; `git status` clean for the `.img` (no rebuild). Guard test `test_groundtruth_year_matches_fixture_mtime` pins `year_inferred`. |

### Neutral observed-fact framing (D-44) — explicitly verified

The persisted tamperability `detail` is the verbatim observed-fact string from
`shell_history.py:179-184` ("shell history is editable by the subject … its line
order is NOT chronological truth … never as proof of timing or intent (D-44)").
Live scan of the rendered disclosures for accusatory/intent vocabulary
(guilty/malicious/intentionally-hid/culprit/deliberately-deleted) → **NONE found**.
No imputed intent.

### Default-path determinism preserved (CLI-02 / D-48)

Live: default `analyze` (no `--logs`) → `log_findings.disclosures == []`, 0 "tamper"
occurrences; two plain `analyze` runs produced **byte-identical** report.json AND
report.html. `timeline_events` schema untouched (D-47 — `log_findings` is additive).
No new wall-clock in `logs.py`/`assemble.py` (non-comment grep == 0). D-14 seam
allowlist intact (`import pytsk3|pyewf` in `log/` + `core/logs.py` == 0). EXT-01
`LogParser.parse` protocol unchanged (`registry.py` last touched 05-01;
`findings_for` is an additive concrete accessor).

### Gap-closure code review (05-REVIEW-gaps.md)

Adversarial standard review of the 10 changed files: **0 critical**, 4 warning, 5
info. The reviewer explicitly cleared SQL parameterization, transaction atomicity /
sole-writer, neutral framing, Jinja2 autoescape (XSS), and default-path determinism
as **No BLOCKER**. The 4 warnings (GR-WR-01..04 above) are robustness/framing nits
that do not defeat any LOG/TIME/SEARCH requirement or core invariant — carried as
non-blocking open warnings.

### Gap-closure observable truths (added to base 14)

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 15 | After `analyze --logs`, the rendered report (json + html) surfaces the D-44 tamperability AND D-45 completeness disclosures as neutral observed-fact (G-2) | ✓ VERIFIED | Live e2e: report.json tamper=1, report.html tamper=4, 6 disclosures categories `['completeness','tamperability']`, no intent language; persisted via single transaction; rendered via `assemble.py` disclosures + `report.html.j2` |
| 16 | D-46 fixture year inference is internally consistent and the committed image was not rebuilt (G-1) | ✓ VERIFIED | `1700000000`→2023-11-14 UTC → year 2023/prev 2022; constants + sidecar + guard test agree; image sha256 unchanged, git clean for `.img` |

**Re-verification score:** 16/16 truths verified (base 14 regression-checked + 2 gap-closure truths).

### Commit & test verification

All 8 task commits exist with correct TDD test→feat ordering: `2c5cfaa`(test)→
`af928bd`(feat), `90e5795`(test)→`a9e2bc0`(feat), `392d249`(test)→`49fbb6a`(feat)
[05-05]; `5670ccd`(fix)→`cc2ce16`(test) [05-06]. Full suite **220 passed** (was 211
at base; +9 from gap-closure tests — matches SUMMARY claims of 219 then 220).

---

# Base-Phase Verification (preserved — 2026-05-31)

## Summary

All 7 phase requirements (LOG-01..04, TIME-02, SEARCH-01, SEARCH-02) are achieved
in the actual codebase, not merely in SUMMARY claims. The three Critical defects a
prior deep review found (CR-01/02/03) — which a green test suite had masked — are
independently confirmed FIXED on the **real orchestrated path**, not just in unit
tests. The core invariants hold: single native seam (D-14), CaseStore sole writer,
read-only forensic soundness, no new runtime dependency (D-43), and CLI-02
determinism (no wall-clock leak). Full suite: **211 passed** (now 220 post-closure).

## Goal Achievement

### Observable Truths (merged ROADMAP success criteria + PLAN must_haves)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `pyautopsy logs <image> --case <dir>` surfaces auth.log/secure login/SSH/sudo/failed-auth events | ✓ VERIFIED | `log/auth.py:36-48` taxonomy (Accepted=ssh-login, Failed password=failure, sudo granted/denied, session opened/closed); CLI `logs` cmd `cli/main.py:346`→`run_logs`; test_logs.py orchestrated test asserts `by_source["auth"]` |
| 2 | Rotated/compressed auth sets reassembled oldest→newest | ✓ VERIFIED | `discover.order_rotated_set` (order_key `(-index, gz)`), `decode_member` gzip inflate; gz fixture in make_fixtures |
| 3 | RFC3164 → UTC via image tz (/etc/localtime→/etc/timezone), tz AND year flagged per event; undeterminable tz → UTC+warning | ✓ VERIFIED | `timeresolve.resolve_host_tz` + `to_utc` emits `timestamp_source`/`assumed_timezone`/`time_warning`; `infer_years` emits `year_inferred`/`year_basis` |
| 4 | syslog/messages (service/kernel/cron/error) parsed into timeline | ✓ VERIFIED | `log/syslog.py` name="syslog", matches syslog/messages; **orchestrated** `iter_parsers()` yields syslog (confirmed in fresh process); test asserts `by_source["syslog"]` non-empty via run_logs |
| 5 | Per-user .bash_history/.zsh_history parsed; epoch used when present else flagged no-timestamp + tamperability finding | ✓ VERIFIED | `log/shell_history.py` no-ts basis flag + D-44 tamperability finding; `discover_shell_histories` per-user sets; test asserts `actor=="user=alice"`. (Surfacing into report now closed by G-2 — see truth 15.) |
| 6 | Both Wave-2 parsers register into shared registry + flow through unchanged run_logs (EXT-01) | ✓ VERIFIED | `log/__init__.py:33-37` imports auth+shell_history+syslog for registration side-effect; `core/logs.py:54` imports package; `_parse_log_set` uses `iter_parsers()` |
| 7 | All log events normalized into shared TimelineEvent model identical to filesystem events (LOG-04) | ✓ VERIFIED | `log/normalize.to_event` → TimelineEvent rows; written via `insert_timeline_events` into same `timeline_events` table |
| 8 | Super-timeline merges fs + log events into one UTC-sorted view (TIME-02) | ✓ VERIFIED | `core/logs.py:382-390` builds fs MACB events + log events into one table; `assemble.py:311` reads `get_timeline_events` with **no new ORDER BY** (comment 421-422); test_supertimeline asserts interleaved + sorted |
| 9 | `pyautopsy search --term` gives hits with file+offset across allocated content + unallocated + metadata | ✓ VERIFIED | `core/search.py` content arm via `search_image` (allocated+unallocated), hash arm metadata region; CLI `search` cmd `cli/main.py:582` |
| 10 | Boundary-spanning match found exactly once with correct absolute offset | ✓ VERIFIED | search/content streaming overlap logic; test_search.py boundary test passes |
| 11 | IOC lists + known-bad-hash sets match (reusing Phase-4 filter infra), report by file+offset | ✓ VERIFIED | `search/ioc.py` reuses filter/hashsets `match_bad_hashes`; hash hits emitted as term_kind="hash" SearchHit + neutral KnownMatch |
| 12 | All reads through two existing seams read-only; unallocated via new iter_unallocated_blocks; search/ imports no pytsk3 | ✓ VERIFIED | `filesystem.py:582 iter_unallocated_blocks`; D-14 grep: only recover/walk/filesystem/image import pytsk3 (walk/recover are docstring-only); test_seam_allowlist 4 passed |
| 13 | `analyze --logs --search <term>` → ONE report with merged super-timeline + log-findings + search-results sections | ✓ VERIFIED | `analyze.py:347 if logs: run_logs`, `:358 if search_requested: run_search`; `assemble.py` log_findings (455) + search_results (491) sections |
| 14 | Default `analyze` byte-identical to Phase-4 baseline (CLI-02, D-48); two --logs runs byte-identical incl tied events (CR-01) | ✓ VERIFIED | test_reproducibility: test_default_analyze_unchanged, test_two_analyze_runs_byte_identical_report, test_tied_log_events_stable, test_tied_log_events_null_meta_tiebreak all pass; no wall-clock in logs.py (confirmed). Re-confirmed live post-closure: default report.json/html byte-identical. |

**Base score:** 14/14 truths verified

## Critical-Fix Confirmation (independent, on the orchestrated path)

| CR | Was | Fix Verified | Evidence (codebase, not SUMMARY) |
|----|-----|--------------|----------------------------------|
| CR-01 | syslog+shell-history dead on real CLI path (only auth imported/discovered) | ✓ HOLDS | Fresh-process import of ONLY `pyautopsy.core.logs` → `iter_parsers()` yields `['auth','shell-history','syslog']`. `__init__.py:33-37` registers all three; `discover.DEFAULT_LOG_BASENAMES` adds syslog/messages; `discover_shell_histories` finds .bash_history/.zsh_history; orchestrator calls BOTH discover fns (`logs.py:350-353`). Regression test `test_run_logs_orchestrated_emits_syslog_and_shell_history` genuinely drives `run_logs`. |
| CR-02 | `datetime.now()` wall-clock year seed leaks into persisted ts_utc → CLI-02 break | ✓ HOLDS | `inspect.getsource(logs)` contains NO `datetime.now`. `_seed_year_from_mtime` chain is member mtime → newest mtime in set → epoch year 1970 (flagged) — every branch evidence-derived/deterministic. |
| CR-03 | month-only RFC3164 year inference + single-line cascade mis-dates timeline | ✓ HOLDS | `infer_years` compares `(month,day)` tuples; cascade guard requires next-older record also in H2 so a lone out-of-order line is absorbed. Verified live: `[(12,20),(1,5)] seed 2026 → [2025,2026]`; `[(1,2),(1,20)] → [2026,2026]`. |

## Core Invariant Checks

| Invariant | Status | Evidence |
|-----------|--------|----------|
| D-14 single native seam | ✓ | Only recover/walk/filesystem/image import pytsk3; test_seam_allowlist passes; `log/`+`core/logs.py` pytsk3/pyewf imports == 0 (re-confirmed post-closure) |
| CaseStore sole writer | ✓ | run_logs/run_search persist via single `store.transaction()` + insert_*; findings persisted in the SAME transaction (no second writer) |
| Read-only forensic soundness | ✓ | assert_source_not_mounted before+after open in both orchestrators; image opened read-only; fixture sha256 unchanged after all runs |
| CLI-02 determinism | ✓ | No datetime.now in logs.py/assemble.py; reproducibility tests + live default-path byte-identity pass |
| D-43 no new runtime dep | ✓ | test_no_new_deps passes; gap-closure added no third-party dependency |
| D-47 timeline_events schema untouched | ✓ | `log_findings` is additive; schema diff touches only the new block |

## Requirements Coverage

| Requirement | Source Plan | Status | Evidence |
|-------------|-------------|--------|----------|
| LOG-01 (auth) | 05-01, 05-04 | ✓ SATISFIED | auth.py taxonomy + run_logs + logs CLI |
| LOG-02 (syslog/messages) | 05-02, 05-04, 05-05, 05-06 | ✓ SATISFIED | syslog.py registered + orchestrated emit confirmed (CR-01 fix) |
| LOG-03 (shell history, noting tamperability) | 05-02, 05-04, **05-05** | ✓ SATISFIED | shell_history.py + discover_shell_histories + tamperability finding NOW SURFACED in report (G-2 closed) — fulfils "noting tamperability" |
| LOG-04 (shared event model) | 05-01, 05-04 | ✓ SATISFIED | normalize.to_event → TimelineEvent into shared table |
| TIME-02 (super-timeline) | 05-01, 05-04, 05-06 | ✓ SATISFIED | get_timeline_events merged read, no new ORDER BY; test_supertimeline; G-1 year reconciliation keeps the timeline self-documenting |
| SEARCH-01 (literal/regex across allocated/unalloc/content) | 05-03, 05-04 | ✓ SATISFIED | search/content + iter_unallocated_blocks seam |
| SEARCH-02 (IOC + known-bad-hash) | 05-03, 05-04 | ✓ SATISFIED | search/ioc reuses filter/hashsets |

No orphaned requirements: REQUIREMENTS.md maps exactly LOG-01..04, TIME-02,
SEARCH-01/02 to Phase 5; all 7 are claimed by plans and verified. The gap-closure
plans 05-05 (LOG-03/LOG-02/LOG-01) and 05-06 (TIME-02/LOG-01/LOG-02) declare only
already-mapped Phase-5 IDs; no new requirement introduced, none orphaned.

## Behavioral Spot-Checks (re-verification, run live)

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `analyze --logs` surfaces tamper disclosure | `grep -c tamper report.json` / `report.html` | 1 / 4 | ✓ PASS |
| Disclosures carry both categories | json `log_findings.disclosures` | 6 rows, `['completeness','tamperability']` | ✓ PASS |
| Neutral framing (no imputed intent) | scan for accusatory/intent vocab | NONE | ✓ PASS |
| Default analyze keeps disclosures empty | json `log_findings.disclosures` | `[]`, 0 tamper | ✓ PASS |
| Default analyze byte-identical (2 runs) | `diff report.json` + `report.html` | identical | ✓ PASS |
| G-1 anchor decodes consistently | `fromtimestamp(1700000000, utc)` | 2023-11-14, year 2023/prev 2022 | ✓ PASS |
| Image not rebuilt | `sha256sum` before/after; `git status` | `6e41afad…079b0` unchanged, clean | ✓ PASS |
| D-14 seam allowlist | grep pytsk3/pyewf in log/+core/logs.py | 0 | ✓ PASS |
| No wall-clock | grep datetime.now in logs.py/assemble.py | 0 / 0 | ✓ PASS |
| Full suite | `PYTHONPATH=src python -m pytest -q` | 220 passed | ✓ PASS |

## Anti-Patterns Found

None goal-blocking. No unreferenced TBD/FIXME/XXX debt markers in the gap-closure
modified files. The per-history unconditional tamperability finding and per-set
completeness finding (GR-WR-02/04) are deliberate D-44/D-45 standing caveats, not
hollow stubs — they emit real, deterministic disclosure rows.

## Human Verification Required

None. All success criteria — including the two closed gaps — are programmatically
verifiable from the committed fixture image and the test suite; verified live in
this re-verification. No visual/UX/external-service surface.

## Gaps Summary

No gaps. The phase goal is achieved end-to-end: the merged UTC super-timeline
(fs + auth + syslog + shell-history) and literal/regex/IOC/known-bad-hash search are
wired through the orchestrated CLI path; default analyze stays byte-identical to the
Phase-4 baseline; the three previously-masked Critical defects remain fixed; and the
two HUMAN-UAT gaps are now closed and independently confirmed against the codebase:
G-2 (D-44 tamperability + D-45 completeness disclosures surfaced in the report with
neutral observed-fact framing) and G-1 (fixture/sidecar year inference reconciled to
2023/2022 with the committed image unchanged). Success Criterion #2 ("…noting
tamperability and log completeness as findings") is now observably met. The carried
open warnings (base WR-01..06 + gap-closure GR-WR-01..04, IN-01..05) are non-blocking
quality/robustness/framing items; none defeats a Phase-5 requirement or a core
invariant (D-14, sole-writer, read-only, CLI-02, D-47).

---

_Verified: 2026-06-01 (gap-closure re-verification); base 2026-05-31_
_Verifier: Claude (gsd-verifier)_
