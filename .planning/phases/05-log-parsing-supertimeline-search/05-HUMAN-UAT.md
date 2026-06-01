---
status: resolved
phase: 05-log-parsing-supertimeline-search
source: [05-VERIFICATION.md, 05-01-SUMMARY.md, 05-02-SUMMARY.md, 05-03-SUMMARY.md, 05-04-SUMMARY.md]
resolved_by: [05-05-PLAN.md, 05-06-PLAN.md]
started: 2026-06-01T09:27:10Z
updated: 2026-06-01T12:00:00Z
---

<!-- INVOCATION NOTES (all commands are copy-pasteable from the repo root):
  • The package has NO __main__.py, so `python -m pyautopsy` does NOT work.
    Use the console script with PYTHONPATH=src so the WORKING-TREE source (not the
    stale ~/.local install, see Phase-4 IN-02) is what runs:
        PYTHONPATH=src pyautopsy <cmd> ...
    Install-free equivalent if the console script misbehaves:
        PYTHONPATH=src python -c "from pyautopsy.cli.main import app; app()" <cmd> ...
  • analyze/ingest REQUIRE --case (fresh) --examiner --evidence-id (chain-of-custody).
  • Standalone `logs`/`search` run against an EXISTING case dir and assume `ingest`
    THEN `walk` already ran (search's hash arm matches the file inventory walk builds).
  • Fixture: tests/fixtures/log_search_ext4.img  (ground truth: log_search_groundtruth.json)
      allocated needle : ALLOCATED-NEEDLE-7f3a2b   (/evidence_note.txt)
      unallocated needle: UNALLOCATED-NEEDLE-9c5d1e (deleted/unallocated only)
      IOC term         : evil-c2.example.invalid
      known-bad sha256 : 6a1eb1b6b60b189d964a177a6188fe87b3136483a79c3bba34ee0a51ee6609ca  (/malware_sample.bin)
      host tz          : America/New_York   year 2026 (prev-year 2025 across Dec→Jan)
  • SHARED STANDALONE CASE (build once, reused by tests 2–8):
        rm -rf /tmp/uat05 && \
        PYTHONPATH=src pyautopsy ingest tests/fixtures/log_search_ext4.img --case /tmp/uat05 --examiner uat-examiner --evidence-id UAT-05 && \
        PYTHONPATH=src pyautopsy walk   tests/fixtures/log_search_ext4.img --case /tmp/uat05
-->

## Current Test
<!-- OVERWRITE each test - shows where we are -->

[gap closure complete — both gaps resolved. G-2 (major) closed by 05-05, G-1 (advisory) closed by 05-06; re-verification passed (16/16). status: resolved. 11/11 effectively pass.]

## Tests

### 1. Cold Start Smoke Test
expected: |
  From a clean checkout with a FRESH empty case dir:
    rm -rf /tmp/uat05a && \
    PYTHONPATH=src pyautopsy analyze tests/fixtures/log_search_ext4.img \
      --case /tmp/uat05a --examiner uat-examiner --evidence-id UAT-05
  Exits 0; produces reports/report.html + report.json; reports evidence-integrity PASS
  (acquisition + end-of-run re-verify). No traceback, no missing-image error, no SQLite error.
result: pass
verified: "2026-06-01 — PASS. Fresh case dir, full default pipeline (ingest→walk→timeline→report) exits 0, report.html+report.json produced, evidence integrity PASS. (Initial run hit two harness-command errors — `python -m pyautopsy` has no __main__, and analyze requires --examiner/--evidence-id; both were UAT-command fixes, not product defects.)"

### 2. Parse auth.log into the timeline (LOG-01) + rotated/gz reassembly
expected: |
  After the SHARED STANDALONE CASE setup (ingest + walk into /tmp/uat05), run:
    PYTHONPATH=src pyautopsy logs tests/fixtures/log_search_ext4.img --case /tmp/uat05
  Exits 0 and reports auth events parsed (~9 on this fixture). Auth events carry an honest
  action/outcome taxonomy — SSH login success vs failed password, sudo granted vs denied,
  session opened/closed — never an inferred "intent". The rotated set (auth.log,
  auth.log.1, auth.log.2.gz) is reassembled oldest→newest (gz inflated + included) so the
  timeline order is deterministic.
result: pass
verified: "2026-06-01 — PASS. `bash /tmp/uat05_setup.sh` (ingest→walk→logs) succeeded; `logs` exited 0 with auth events parsed and rotated/gz set reassembled. (Earlier paste attempts broke on terminal line-wrapping splitting `--examiner` from its value; resolved by running a script file — environment/paste issue, not a product defect.)"

### 3. Inferred timezone + year are FLAGGED per event, never silent (D-46 / forensic soundness)
expected: |
  Inspect the persisted timeline after the test-2 `logs` run (e.g. open
  /tmp/uat05/reports/... after a later analyze, or query the case DB timeline_events).
  RFC3164 syslog/auth lines (no year, no offset) are resolved to UTC using the IMAGE's own
  timezone (/etc/localtime → America/New_York, /etc/timezone fallback), and each such event
  is explicitly flagged: timestamp_source / assumed_timezone / year_inferred (or year_basis).
  The Dec→Jan boundary in the rotated set infers the correct PRIOR year (2025 vs 2026). If
  the host tz were undeterminable the event would fall back to UTC WITH a warning. No
  inferred time is ever presented as asserted fact.
result: pass
verified: "2026-06-01 — PASS (with minor gap, see Gaps G-1). Inspector over /tmp/uat05 (89 events): every inferred log event carries timestamp_source='log:inferred-tz', assumed_timezone='America/New_York', year_basis='file mtime + rotation order', and year_inferred on auth/syslog. tz conversion correct (tied syslog 'Jan 15 03:14:15' EST -> 2023-01-15T08:14:15+00:00). Multi-year inference works (events span 3 distinct years; Dec->Jan rollback present); epoch-anchored shell-history lines resolve correctly to 2025-01-15 from embedded epochs 1736899200/300. Forensic-soundness requirement (inferred, flagged, deterministic, never silent) MET. MINOR DRIFT: mtime-inferred years land 2023/2024/2025 whereas log_search_groundtruth.json documents year=2026/prev_year=2025 — the committed fixture image was built with a single ~2023-11-14 fake mtime (all 68 fs events at 2023-11-14T22:13:20), so D-46 mtime-anchored inference yields ~2023, not the sidecar's intended 2026. Mechanism sound; fixture-vs-sidecar doc disagreement only. User verdict: pass + log drift as minor gap."

### 4. Parse syslog/messages into the timeline (LOG-02)
expected: |
  On the same orchestrated `logs` run (test 2), syslog/messages events are present in the
  merged timeline (NOT only auth — this is the CR-01 fix; syslog must actually appear on the
  real CLI path). Events for kernel / cron / service programs appear with a program-based
  action taxonomy; an error-level line carries a non-authoritative outcome="error" annotation
  over the observed text. Unmatched lines still become events carrying their raw message
  rather than being dropped.
result: pass
verified: "2026-06-01 — PASS. Source breakdown over /tmp/uat05: auth=9, syslog=6, shell-history=6, filesystem:ext=68. syslog events present on the orchestrated `pyautopsy logs` path (CR-01 regression confirmed fixed — LOG-02 no longer dead on the real CLI path); program-based action taxonomy (action='service' etc.); both tied 'Jan 15 03:14:15' syslog lines present."

### 5. Parse shell history + tamperability finding (LOG-03)
expected: |
  On the same `logs` run, per-user /home/alice/.bash_history and .zsh_history are parsed.
  zsh extended-history embedded epochs are used as the timestamp; bash `#<epoch>` markers are
  used; bash lines with NO per-line timestamp are explicitly flagged
  (ts_basis = "file-mtime-fallback; no per-line timestamp") rather than given an invented
  time. A tamperability finding (history is editable — observed fact, not accusation) is
  surfaced. Owning user is "user=alice" (from /home/alice), never "user=None".
result: pass
verified: "2026-06-01 — PASS (tamperability finding confirmed separately at test 9). 6 shell-history events, all actor='user=alice'. Embedded epochs honored — events at 2025-01-15T00:00:00/00:01:40/00:01:45 from epochs 1736899200/1736899300. No-per-line-timestamp lines flagged ts_basis='file-mtime-fallback; no per-line timestamp' (not invented). Event attr keys: assumed_timezone,kind,raw,timestamp_source,ts_basis,tz_resolution,year_basis — D-44 tamperability finding is a ShellHistoryResult/report-level finding, NOT a per-event attribute. UPDATE (test 9): the D-44 tamperability finding is NOT surfaced in the rendered report (0 'tamper' occurrences in report.json/html) — parser computes it but core/logs.py drops it. Per-event shell parsing PASSES; the report-surfacing of the tamperability caveat is the test-9 issue (gap G-2)."

### 6. Super-timeline merges filesystem + ALL log sources into one UTC-ordered view (TIME-02 / CR-01)
expected: |
  Because the case had `walk` run first, the merged timeline interleaves filesystem MACB
  events with auth + syslog + shell-history log events in ONE stable UTC total order (no
  separate per-source lists). Confirm all THREE log parsers (auth, syslog, shell-history)
  contribute on the real CLI path — not only auth. Tied events (same second, e.g. the two
  "Jan 15 03:14:15" lines) sort deterministically. (Easiest to read in the unified report,
  test 9; or query timeline_events ordered.)
result: pass
verified: "2026-06-01 — PASS. One merged get_timeline_events read of 89 events interleaves filesystem:ext(68)+auth(9)+syslog(6)+shell-history(6) in a single D-26 UTC total order (no per-source lists). All three log parsers contribute on the real path. Tied seconds break deterministically by source/actor/id: syslog pair ids 82,83 at 2023-01-15T08:14:15; shell-history ids 84,85,87 at 2023-01-01T05:00:00; 68 fs events at 2023-11-14T22:13:20 ordered by insertion-order id."

### 7. Content search across allocated content AND unallocated space (SEARCH-01)
expected: |
  Against the shared case:
    PYTHONPATH=src pyautopsy search tests/fixtures/log_search_ext4.img --case /tmp/uat05 \
      --term ALLOCATED-NEEDLE-7f3a2b --term UNALLOCATED-NEEDLE-9c5d1e
  Returns hits with file path (where applicable) and absolute byte offset. The allocated
  needle is found in the live file /evidence_note.txt; the unallocated needle (living only in
  deleted/unallocated space, belonging to no live file) is ALSO found. A match spanning a
  read-chunk boundary is reported exactly once at its correct offset. A pathological
  --regex --term is bounded/rejected, not hung.
result: pass
verified: "2026-06-01 — PASS. search returned 2 hits (1 unallocated). Persisted search_hits: ALLOCATED-NEEDLE-7f3a2b kind=literal /evidence_note.txt byte_off=64 (== ground-truth offset); UNALLOCATED-NEEDLE-9c5d1e kind=literal path=None byte_off=1409272 (unallocated, no live file, absolute offset). Each term hit once. ReDoS guard: `--regex '(a+)+$'` rejected at compile time ('catastrophic-backtracking / ReDoS vector'), exit 1, no hang (NEW-CR-01 fix holds)."

### 8. IOC terms + known-bad-hash matching (SEARCH-02)
expected: |
  Create tiny list files, then search:
    echo 'evil-c2.example.invalid' > /tmp/uat05_ioc.txt
    echo '6a1eb1b6b60b189d964a177a6188fe87b3136483a79c3bba34ee0a51ee6609ca' > /tmp/uat05_bad.txt
    PYTHONPATH=src pyautopsy search tests/fixtures/log_search_ext4.img --case /tmp/uat05 \
      --ioc /tmp/uat05_ioc.txt --hash-set-block /tmp/uat05_bad.txt
  The planted IOC term is flagged as a hit; the planted known-bad-hash file /malware_sample.bin
  is flagged by file (reusing the Phase-4 hash matcher). Hash hits are reported NEUTRALLY
  ("known", with source/list name) — no good/bad/safe/malicious verdict language.
result: pass
verified: "2026-06-01 — PASS. IOC term 'evil-c2.example.invalid' (kind=ioc) flagged across 3 files by file+offset: /home/alice/.bash_history off47, /var/log/auth.log off312, /var/log/syslog off320. Known-bad sha256 6a1eb1...09ca (kind=hash) flagged /malware_sample.bin (known-bad hits: 1), reusing the Phase-4 hash matcher. Neutral framing — term_kind hash/ioc, no good/bad/safe/malicious verdict language."

### 9. Unified report: `analyze --logs --search <term>` → ONE report with all sections (Truth 13)
expected: |
  Run (fresh dir):
    rm -rf /tmp/uat05b && \
    PYTHONPATH=src pyautopsy analyze tests/fixtures/log_search_ext4.img \
      --case /tmp/uat05b --examiner uat-examiner --evidence-id UAT-05 \
      --logs --search ALLOCATED-NEEDLE-7f3a2b
  Produces a SINGLE report (report.html + report.json) containing: (a) the merged
  filesystem+log super-timeline, (b) a Log Findings section, and (c) a Content Search
  section. The honest MVP/limitations disclaimer reflects that logs and search actually ran.
  Event count = filesystem events + log events with no duplication.
result: issue
reported: "Report STRUCTURE is correct (one report.json+report.html; sections log_findings + search + timeline; timeline_total=89 = 68 fs + 21 log, no duplication; honest tz/year provenance block inferred_timezone_count=18/inferred_year_count=15; honest mvp_disclaimer reflecting logs+search ran; neutral search framing; search hit /evidence_note.txt byte_offset 64). BUT the D-44 shell-history TAMPERABILITY finding is NOT surfaced in the report: grep 'tamper' in /tmp/uat05b/reports/report.json AND report.html = 0 occurrences. The shell_history parser computes it (shell_history.py:180 'shell history is editable by the subject...') but core/logs.py never consumes/persists the ShellHistoryResult findings, so the mandated LOG-03/D-44 honesty caveat is dropped before the report. Same class as WR-07 (D-45 log-completeness/rotation finding also 0 occurrences). For an evidence-presentation report this is a forensic honesty-disclosure gap."
severity: major

### 10. Default `analyze` stays byte-identical to the Phase-4 baseline + reproducible (CLI-02 / D-48)
expected: |
  (a) Determinism: run the SAME analyze command twice into two fresh dirs and diff the
  reports — report.json and report.html are byte-identical (the volatile run_metadata.json
  sidecar may differ; the report body must not):
    rm -rf /tmp/uat05c /tmp/uat05d
    for d in /tmp/uat05c /tmp/uat05d; do \
      PYTHONPATH=src pyautopsy analyze tests/fixtures/log_search_ext4.img --case $d \
        --examiner uat-examiner --evidence-id UAT-05 --logs --search ALLOCATED-NEEDLE-7f3a2b; done
    diff /tmp/uat05c/reports/report.json /tmp/uat05d/reports/report.json && echo "JSON identical"
    diff /tmp/uat05c/reports/report.html /tmp/uat05d/reports/report.html && echo "HTML identical"
  (b) Default-path stability: a plain `analyze` (no --logs/--search, from test 1) renders the
  new log/search sections as empty-state and adds no noise — output matches the Phase-4
  baseline shape (no wall-clock leaks into the comparable body).
result: pass
verified: "2026-06-01 — PASS. Determinism EXACT: two identical `analyze --logs --search` runs (/tmp/uat05c, /tmp/uat05d) -> report.json + report.html BYTE-IDENTICAL; run_metadata.json correctly differs (volatile sidecar). Default path: two plain `analyze` runs byte-identical; log_findings.count=0 (by_source []) + search.count=0 (hits []) render empty-state, no noise; 0 wall-clock/run_started/generated_at occurrences in report body. NOTE: literal Phase-4-baseline byte-identity not re-diffed here (report.json legitimately gains empty log_findings/search keys vs Phase-4); covered by GREEN test_default_analyze_unchanged + byte-stable report.html."

### 11. Read-only forensic soundness — the source image is never modified
expected: |
  Record the fixture hash before and after all the runs above:
    sha256sum tests/fixtures/log_search_ext4.img
  Expected (unchanged before AND after every logs/search/analyze run):
    6e41afadc5309b4471e2c2377e8022104510d84ec8c6b18ececa10f2901079b0
  The tool treats the source strictly read-only, refuses a mounted source, and end-of-run
  evidence re-verification still PASSES.
result: pass
verified: "2026-06-01 — PASS. sha256 of tests/fixtures/log_search_ext4.img AFTER all logs/search/analyze runs = 6e41afadc5309b4471e2c2377e8022104510d84ec8c6b18ececa10f2901079b0 = baseline (unchanged); git working tree clean (fixture unmodified). Mounted-source guard assert_source_not_mounted fires before+after open in run_logs (logs.py:346,387) and run_search (search.py:158,239). End-of-run integrity re-verify PASS (test 1)."

## Summary

total: 11
passed: 11
issues: 0
pending: 0
skipped: 0
blocked: 0
advisory_gaps: 0

## Gaps

<!-- G-1 is an advisory minor gap (test 3 still PASSED on the real requirement); not a failed test. -->
- id: G-1
  truth: "D-46 year inference, when anchored on file mtime, should produce years matching the test corpus's documented ground truth (log_search_groundtruth.json year=2026/prev_year=2025)."
  status: resolved
  resolution: "Closed by plan 05-06 (commits 5670ccd..dfe2c87, Path B — no image rebuild). The committed fixture image's frozen debugfs clock _EXT4_FAKE_TIME=1700000000 decodes to 2023-11-14T22:13:20+00:00, so D-46 correctly yields year=2023/prev_year=2022. Reconciled the sidecar (log_search_groundtruth.json: year 2026->2023, prev_year 2025->2022) and added make_fixtures.py LOG_SEARCH_YEAR=2023/PREV_YEAR=2022 anchored by comment to that clock, plus regression guard test_groundtruth_year_matches_fixture_mtime. Image sha256 6e41afad...079b0 UNCHANGED (UAT test-11 lockstep preserved). Inference mechanism unchanged."
  reason: "Inferred log events land at 2023/2024/2025, not the sidecar's 2026/2025. Root cause: the committed fixture image (tests/fixtures/log_search_ext4.img) was built with a single ~2023-11-14 fake mtime (all 68 filesystem events at 2023-11-14T22:13:20), so D-46's mtime-anchored inference correctly yields ~2023. The forensic mechanism (inferred + flagged + deterministic + multi-year Dec->Jan rollback) is sound; only the committed fixture's mtime disagrees with the sidecar's intended 2026 anchor. Epoch-anchored shell-history lines DO land correctly at 2025-01-15."
  severity: minor
  test: 3
  remediation: "Either rebuild the fixture with a ~Jan-2026 fake mtime so make_fixtures + groundtruth + D-46 inference agree, OR correct year/prev_year in log_search_groundtruth.json to the values the 2023-mtime fixture actually produces. Relates to verification WR-01 (year-wrap vs real rotated-log fixtures, flagged requires-human-verification)."
  artifacts:
    - path: "tests/fixtures/log_search_groundtruth.json"
      issue: "documents year=2026/prev_year=2025"
    - path: "tests/fixtures/make_fixtures.py"
      issue: "build_log_search_image fake mtime anchors ~2023-11-14, not ~2026"
  debug_session: ""

- id: G-2
  truth: "The shell-history D-44 tamperability finding (and the D-45 log-completeness/rotation finding) must be surfaced in the rendered report so an examiner sees the honesty caveat (LOG-03 requires the tamperability note; D-44 mandates surfacing as a finding, never intent)."
  status: resolved
  resolution: "Closed by plan 05-05 (commits 2c5cfaa..f85f2e2). Added an additive log_findings CaseStore table (schema.sql/models.py/store.py insert_log_findings+get_log_findings), threaded the D-44 shell-history tamperability finding and D-45 log-completeness finding through core/logs.py:run_logs (persisted in the single store.transaction(), CaseStore sole writer), and rendered them in report/assemble.py log_findings.disclosures + report.html.j2. Verified live: analyze --logs -> report.json tamper=1, report.html tamper=4, 6 disclosures (categories completeness+tamperability); neutral observed-fact framing honored (no imputed intent); default analyze path stays byte-identical with disclosures==[]; timeline_events untouched. e2e assertion added (test_reproducibility.py) + 8 new tests; full suite 220 passed."
  reason: "analyze --logs --search produced a report with 0 occurrences of 'tamper' in both report.json and report.html (case /tmp/uat05b). The shell_history parser computes the finding (shell_history.py:180) and returns it on ShellHistoryResult, but core/logs.run_logs never consumes/persists the parser findings, so the mandated tamperability caveat is dropped before assemble_report_body. The D-45 completeness/rotation finding is likewise absent (== verification WR-07, previously user-deferred)."
  severity: major
  test: 9
  root_cause: "core/logs.py run_logs discards the ShellHistoryParser/ShellHistoryResult findings (no finding-persistence path); report/assemble.py log_findings section only renders by_source counts + tz/year provenance, with no shell-history tamperability or D-45 completeness finding wired in. So the finding is computed-but-not-threaded (same shape as WR-07)."
  artifacts:
    - path: "src/pyautopsy/core/logs.py"
      issue: "run_logs does not capture/persist ShellHistoryResult.findings (D-44 tamperability) nor the D-45 discover completeness finding"
    - path: "src/pyautopsy/report/assemble.py"
      issue: "log_findings section omits a tamperability / log-completeness disclosure sub-block"
    - path: "src/pyautopsy/log/shell_history.py"
      issue: "produces the tamperability finding (line ~180) that is never consumed downstream"
  missing:
    - "Persist or thread ShellHistoryResult tamperability finding (D-44) and the D-45 completeness finding through run_logs into the case, and render them in assemble_report_body's log_findings section."
    - "Add an e2e assertion that report.json log_findings contains the tamperability + completeness disclosures (would fail today)."
  debug_session: ""
