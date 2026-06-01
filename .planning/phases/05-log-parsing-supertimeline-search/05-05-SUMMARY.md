---
phase: 05-log-parsing-supertimeline-search
plan: 05
subsystem: log-parsing / case-store / reporting
tags: [gap-closure, G-2, D-44, D-45, honesty-disclosure, determinism]
requires:
  - run_logs orchestrator (05-02/05-04)
  - ShellHistoryResult.findings (D-44) + LogSet.CompletenessFinding (D-45)
  - assemble_report_body log_findings section (03/05)
provides:
  - log_findings table + LogFinding model + insert_log_findings/get_log_findings
  - ShellHistoryParser.findings_for accessor
  - LogsResult.findings_count
  - log_findings.disclosures report sub-block (json + html)
affects:
  - src/pyautopsy/case/* (additive table/model/store path)
  - src/pyautopsy/core/logs.py (findings accumulation + persistence)
  - src/pyautopsy/report/* (disclosures rendering)
tech-stack:
  added: []
  patterns:
    - "Additive findings table mirrors volume_limitations (D-20 analog); timeline_events untouched (D-47)"
    - "CaseStore sole writer; findings persisted in the existing single run_logs transaction (WR-01)"
    - "Store-owned id order for the disclosures read (D-41); no re-sort in the reporter"
    - "Concrete additive accessor (findings_for) avoids changing the EXT-01 LogParser.parse protocol"
key-files:
  created: []
  modified:
    - src/pyautopsy/case/schema.sql
    - src/pyautopsy/case/models.py
    - src/pyautopsy/case/__init__.py
    - src/pyautopsy/case/store.py
    - src/pyautopsy/log/shell_history.py
    - src/pyautopsy/core/logs.py
    - src/pyautopsy/report/assemble.py
    - src/pyautopsy/report/templates/report.html.j2
    - tests/test_case_store.py
    - tests/test_logs.py
    - tests/test_report.py
    - tests/test_reproducibility.py
decisions:
  - "05-05: log_findings is an additive findings table mirroring volume_limitations (D-20 path); timeline_events untouched so D-47/CLI-02 determinism hold (D-47/D-48)"
  - "05-05: D-44/D-45 findings persist in run_logs' existing single transaction — CaseStore stays the sole writer, no second transaction (WR-01)"
  - "05-05: ShellHistoryParser.findings_for additive accessor reaches the dropped findings WITHOUT changing the EXT-01 LogParser.parse record-only protocol"
  - "05-05: tamperability detail persisted VERBATIM from shell_history.py (observed-fact, never intent); completeness detail is discover's neutral note (D-44)"
  - "05-05: report disclosures read in store id order (D-41); default path get_log_findings == [] keeps report.json/html byte-identical (D-48)"
metrics:
  duration: ~22min
  tasks: 3
  files: 12
  completed: 2026-06-01
---

# Phase 05 Plan 05: Surface D-44 Tamperability + D-45 Completeness Disclosures Summary

Closed UAT gap G-2 (MAJOR): the LOG-03/D-44 shell-history tamperability finding and the D-45 log-completeness finding were computed by the parsers/discover but dropped before the report (0 occurrences of "tamper" in the rendered output). They are now threaded from where they are computed, through `run_logs`, persisted in the case via a new additive `log_findings` table, and rendered as a neutral observed-fact disclosure sub-block in both report.json and report.html.

## What Was Built

**Task 1 — Additive `log_findings` store path** (commits `2c5cfaa` RED, `af928bd` GREEN)
- `schema.sql`: additive `log_findings` table (`id`, `evidence_source_id`, `category`, `subject`, `detail`, `attributes`) + `idx_log_findings_evidence_source_id`, mirroring `volume_limitations`. `timeline_events` untouched (D-47).
- `models.py`: `LogFinding` frozen/slots dataclass; re-exported from `pyautopsy.case`.
- `store.py`: `_LOG_FINDING_COLUMNS`/`_LOG_FINDING_INSERT_SQL`/`_log_finding_params` + `insert_log_findings(rows) -> int` (executemany, `_commit_unless_in_transaction`) and `get_log_findings(evidence_source_id) -> list[LogFinding]` (store-owned `ORDER BY id`, D-41).

**Task 2 — Thread findings through `run_logs`** (commits `90e5795` RED, `a9e2bc0` GREEN)
- `shell_history.py`: additive `ShellHistoryParser.findings_for(text, ctx)` accessor returns `parse(...).findings` without touching the EXT-01 `LogParser.parse` record-only protocol (registry.py unchanged).
- `core/logs.py`: one D-45 `completeness` LogFinding per discovered `LogSet` (neutral `note` + present/missing indices in attributes); one D-44 `tamperability` LogFinding per shell-history member (detail persisted verbatim). `_parse_log_set` now returns `(events, findings)`; all findings persisted via `insert_log_findings` inside the existing single `store.transaction()` (WR-01). `LogsResult.findings_count` added; `logs.end` audit records it.

**Task 3 — Render disclosures + determinism + e2e proof** (commits `392d249` RED, `49fbb6a` GREEN)
- `assemble.py`: reads `get_log_findings`, builds `log_findings["disclosures"]` (one dict per row, store id order) + `_LOG_DISCLOSURE_INTRO` neutral observed-fact intro. Default path → `[]`, keeping report bytes unchanged (D-48). No wall-clock reachable.
- `report.html.j2`: guarded `{% if body.log_findings.disclosures %}` block rendering each disclosure (autoescaped, Security V5) inside the Log Findings `<section>`; default-path HTML unchanged.

## Verification

- Full suite: `PYTHONPATH=src python -m pytest -q` → **219 passed** (was 211; 8 new tests).
- TDD gates honored per task: failing `test(...)` commit then passing `feat(...)` commit. New tests' docstrings record that the same assertions fail on pre-fix main (the G-2 drop point).
- e2e (UAT test 9 mirror): `analyze tests/fixtures/log_search_ext4.img ... --logs --search ALLOCATED-NEEDLE-7f3a2b` → `grep -c tamper report.json` = **1**, `report.html` = **4** (both were 0 on main).
- Default-path determinism: two plain `analyze` runs → report.json AND report.html byte-identical (`diff` clean); `log_findings.disclosures == []`.
- `grep -rn "import pytsk3\|import pyewf" src/pyautopsy/log/ src/pyautopsy/core/logs.py` == 0 (D-14 seam allowlist intact).
- No new wall-clock in assemble.py / logs.py; no new third-party dependency (D-43); ruff + mypy clean on all modified source.

## Critical Invariants Held

- CaseStore is the sole writer; findings inserted in the existing single `store.transaction()` (no second transaction).
- `log_findings` is additive (mirrors the D-20 volume_limitations path); `timeline_events` schema untouched (D-47).
- Default `analyze` (no `--logs`) report.json/report.html stay byte-identical (D-48/CLI-02).
- No new third-party dependency (D-43); EXT-01 `LogParser.parse` protocol unchanged.
- D-44 disclosure framing is verbatim, neutral, observed-fact (editable-by-subject, not intent).

## Deviations from Plan

None — plan executed exactly as written. One in-test fix during Task 1 GREEN (reading a second evidence source's findings was moved inside the `with CaseStore` block to avoid a closed-DB read in the test itself; not a deviation in product code).

## Self-Check: PASSED

- Modified files present and committed (12 files across 6 commits).
- Commits verified in `git log`: `2c5cfaa`, `af928bd`, `90e5795`, `a9e2bc0`, `392d249`, `49fbb6a`.
- e2e tamper counts > 0; default-path byte-identity confirmed.
