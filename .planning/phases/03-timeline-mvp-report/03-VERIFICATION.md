---
phase: 03-timeline-mvp-report
verified: 2026-05-31T13:16:37Z
status: human_needed
score: 5/5 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: null
  note: "Initial verification (no prior VERIFICATION.md)."
human_verification:
  - test: "Run `pyautopsy analyze <image> --case <fresh-dir> --examiner ... --evidence-id ...` on a LARGE, real, partitioned disk image (multi-GB, multiple volumes, mixed ext4/FAT/NTFS)."
    expected: "Completes in one process, produces reports/report.{html,json} + run_metadata.json; HTML timeline truncates with an honest 'Showing N of M' note when events exceed the 2000 cap; per-volume breakdown lists each real volume; integrity section reflects the real acquisition-hash outcome."
    why_human: "Fixtures are tiny single-volume images; bounded-timeline truncation, multi-volume aggregation, and large-image performance/feel cannot be exercised by the committed test fixtures."
  - test: "Open the rendered report.html in a browser and visually inspect the eight sections, the FAIL/NOT-COMPARED status banner styling, and print-to-PDF (A4) layout."
    expected: "Sections render in canonical order; status is text+glyph (never color-only); FAIL banner is prominent near the top; A4 print has no clipped cards; long hashes/paths wrap."
    why_human: "Visual appearance, print layout, and color-independence are not programmatically verifiable."
  - test: "Supply a CORRECT --acquisition-hash and a WRONG --acquisition-hash on real images and inspect the integrity section of report.json/html."
    expected: "Correct hash → PASS copy ('source hash matches acquisition value'); wrong hash → ingest FAILs and rolls back (no report), or the FAIL copy renders if a report is assembled over a recorded mismatch; no acquisition hash → NOT COMPARED copy."
    why_human: "The FAIL render path is only reachable when ingest persists a mismatch; end-to-end FAIL behavior on a real mismatched acquisition value is best confirmed manually (the unit test covers the three states at the assemble layer, but not the live ingest-FAIL rollback interaction)."
---

# Phase 3: Timeline & MVP Report Verification Report

**Phase Goal:** An examiner runs one command and gets a complete, reproducible forensic report (human-readable + structured) from a disk image — closing the end-to-end MVP vertical slice and proving the spine before more producers are added.
**Verified:** 2026-05-31T13:16:37Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Success Criteria (ROADMAP acceptance bar)

| # | Success Criterion | Verdict | Evidence |
|---|-------------------|---------|----------|
| 1 | Chronological timeline (bodyfile/mactime) from filesystem MACB metadata, UTC-ordered with explicit offsets | ✓ VERIFIED | `timeline/builder.py` `_explode` emits one event per populated `*_utc` (M/A/C/B → modified/accessed/changed/born), copies `ts_utc` verbatim (no re-derivation); `store.get_timeline_events` orders by the 9-key total order; `ts_utc` carries explicit `+00:00`. `test_macb_explosion`, `test_total_order`, `test_ext4_timeline` pass. |
| 2 | Human-readable HTML/Markdown report: case/COC, methodology + tool/TSK versions, findings, evidence hashes, timeline, limitations (no overclaiming) | ✓ VERIFIED | `report.html.j2` renders 8 sections incl. methodology (`tsk_version`/`pyautopsy_version`), evidence hashes, timeline, mandatory Limitations + MVP disclaimer; integrity copy is honest (PASS/FAIL/NOT COMPARED). `test_findings_d28`, `test_versions_recorded`, `test_html_autoescape`, `test_integrity_three_states_honest`, `test_fat_provenance` pass. |
| 3 | Structured machine-readable JSON report alongside the human report | ✓ VERIFIED | `jsonreport.write_json` serializes the full body (incl. unabridged D-26 timeline) with `sort_keys=True, ensure_ascii=False`, confined to `reports/`. `test_json_report` passes; analyze writes both `report.json` and `report.html`. |
| 4 | Single command `pyautopsy analyze <image> --case ...` produces the complete report set | ✓ VERIFIED | `core/analyze.run_analyze` composes ingest→walk→build_timeline→assemble→write_json→render_html in one process; CLI `analyze` command exposes the full D-21 surface (verified via `--help`). `test_analyze_produces_reports` + `test_analyze_composes_pipeline` pass (cases/sources/files/timeline_events all present; re-verify audited). |
| 5 | Two runs on same fixture → BYTE-IDENTICAL report bodies (run metadata segregated); TSK/tool versions pinned + recorded | ✓ VERIFIED | `test_two_analyze_runs_byte_identical_report` asserts whole-file byte-equality on BOTH report.json AND report.html, excludes run_metadata.json, and asserts run_metadata.json `generated_utc` DIFFERS. Body carries no wall-clock; versions recorded in `methodology`. |

**Score:** 5/5 success criteria verified

### Observable Truths (PLAN must_haves)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | timeline_events table + D-26 ordering index in fresh case.db | ✓ VERIFIED | schema.sql:129-155; index = 9 columns matching ORDER BY. |
| 2 | CaseStore persists/reads TimelineEvent in total order | ✓ VERIFIED | store.py:505-525 insert, 527-566 ordered read (LIMIT supported). |
| 3 | build_timeline = one event per populated MACB; None → no event; ts_utc verbatim | ✓ VERIFIED | builder.py:62-81; `if ts is None: continue`; `ts_utc=ts` verbatim. |
| 4 | assemble_report_body deterministic, no wall-clock reachable, 8 sections + timeline_total | ✓ VERIFIED | assemble.py:99-332; `grep datetime.now/utc_now/iso_utc` empty; `timeline_total` present. |
| 5 | JSON full timeline; HTML bounded slice + honest truncation | ✓ VERIFIED | jsonreport full body; htmlreport `body["timeline"][:cap]`, template "Showing N of M". |
| 6 | Evidence strings autoescaped; no `\| safe` on evidence | ✓ VERIFIED | `select_autoescape(["html","j2"])`; `test_html_autoescape` asserts `&lt;script&gt;` present, raw `<script>` absent. |
| 7 | report.html carries ZERO run metadata | ✓ VERIFIED | grep for run_metadata/generated_utc/durations/run_id in template = empty. |
| 8 | analyze composes pipeline; ingest/walk standalone; Phase 1 re-verify runs | ✓ VERIFIED | analyze.py composes run_ingest/run_walk; ingest/walk commands intact (test_cli_smoke/ingest/walk green); re-verify runs inside run_ingest, audited. |
| 9 | Two analyze runs byte-identical; run metadata in sidecar, differs | ✓ VERIFIED | test_reproducibility.py:147-188. |

### CR-01 / WR-01..05 Fix Verification (from 03-REVIEW.md)

| Finding | Fix Verdict | Evidence |
|---------|-------------|----------|
| CR-01 (D-26 not total — NULL meta_addr ties) | ✓ FIXED | ORDER BY extended to `ts_utc, volume_id, volume_offset, path, event_type, meta_addr, source, actor, id` (store.py:559-560); index updated (schema.sql:151-155); docstring corrected to drop the false "can never tie" claim. Regression test `test_total_order_null_meta_addr_is_deterministic` covers distinct events tying on six keys with NULL meta_addr, separated by source/actor/id, and asserts repeated reads are identical. |
| WR-01 (sidecar skips confinement guard) | ✓ FIXED | `_write_run_metadata` routes through `_confined_reports_dir` (analyze.py:147). |
| WR-02 (hardcoded integrity PASS) | ✓ FIXED | Three honest states derived from `acquisition_verified` (assemble.py:230-243); `test_integrity_three_states_honest` asserts NOT COMPARED when no hash, PASS only when matched. |
| WR-03 (per-volume fs_type ambiguity) | ✓ FIXED | Non-null fs_type preferred (assemble.py:163-164). |
| WR-04 (misleading confinement docstring) | ✓ FIXED | Docstring scoped to directory confinement + fixed-name files (jsonreport.py:44-51). |
| WR-05 (actor emits literal `gid=None`) | ✓ FIXED | Only populated uid/gid parts joined (builder.py:51-56). |

### D-14 Native Seam

| Check | Status | Evidence |
|-------|--------|----------|
| Phase 3 code imports no pytsk3/pyewf | ✓ VERIFIED | grep across `timeline/`, `report/`, `core/analyze.py` returns nothing; analyze composes the seam via orchestrators only. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full test suite | `python -m pytest -q` | 173 passed | ✓ PASS |
| Lint | `ruff check .` | No issues found | ✓ PASS |
| Types | `mypy src` | No issues found | ✓ PASS |
| analyze CLI surface | `analyze --help` | Lists --case/--examiner/--evidence-id/--acquisition-hash/--timezone/--max-hash-size | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| TIME-01 | 03-00, 03-01 | Chronological timeline from filesystem MACB | ✓ SATISFIED | builder.py MACB explosion; total-order read; value-level `test_total_order` + NULL-meta_addr regression. |
| REPORT-03 | 03-00, 03-02 | Human-readable report (COC, methodology+versions, findings, hashes, timeline, exhibits) | ✓ SATISFIED | report.html.j2 8 sections; honest integrity (no overclaim); limitations mandatory; tests green. |
| REPORT-04 | 03-00, 03-02 | Structured machine-readable JSON report | ✓ SATISFIED | jsonreport.write_json full body, sorted-key UTF-8; `test_json_report`. |
| CLI-01 | 03-00, 03-03 | Single-command full analysis | ✓ SATISFIED | run_analyze + analyze command compose ingest→walk→timeline→report; ingest/walk intact; re-verify runs. |
| CLI-02 | 03-00, 03-02, 03-03 | Deterministic, reproducible output; versions pinned/recorded | ✓ SATISFIED | byte-identical report.json+html across runs; run metadata segregated to sidecar; versions in methodology. |

All 5 declared requirement IDs (TIME-01, REPORT-03, REPORT-04, CLI-01, CLI-02) are claimed by plans, map to Phase 3 in REQUIREMENTS.md (lines 131-140), and are satisfied. No orphaned requirements for Phase 3.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| core/analyze.py | 269 | `durations={}` always empty (IN-04) | ℹ️ Info | Run-metadata sidecar never records per-stage timings; non-analytical, outside the determinism contract. No SC impact. Reviewer-deferred. |
| timeline/builder.py | 85 | `explode = _explode` public alias (IN-02) | ℹ️ Info | Redundant indirection; no behavioral impact. Reviewer-deferred. |
| report/assemble.py | 189 | `repr(sorted(...))` dedup marker (IN-03) | ℹ️ Info | Works for flat str→str; fragile idiom. No correctness impact for current shape. Reviewer-deferred. |
| report/templates/report.html.j2 | 236, 265 | Truncation disclosure rendered twice (IN-01) | ℹ️ Info | Intentional top+bottom; copy could drift. No correctness impact. Reviewer-deferred. |

No 🛑 Blocker or unreferenced debt markers (no TBD/FIXME/XXX) found in phase files.

### Notable Test-Coverage Gap (non-blocking)

| Item | Severity | Detail |
|------|----------|--------|
| Fresh-case guard (A2) lacks an automated test | ⚠️ Info/Warning | Plan 03-03 acceptance criteria stated "re-running analyze into a dir that already has case.db raises AnalyzeError (fresh-case test passes)", but no such test exists in tests/test_analyze.py. The guard IS implemented and reachable (analyze.py:203-208) and documented in `--help`. It is a determinism safeguard, NOT one of the 5 ROADMAP success criteria, so it is not a blocker — but the asserted regression test is missing. Recommend adding `test_analyze_refuses_existing_case` in a follow-up. |

### Human Verification Required

1. **Large real partitioned-disk analyze run** — run analyze on a multi-GB, multi-volume mixed-filesystem image and confirm one-command completion, timeline truncation note, per-volume breakdown, and performance. The committed fixtures are tiny single-volume images and cannot exercise these.
2. **Visual + print inspection of report.html** — confirm section order, text+glyph status encoding (color-independent), prominent FAIL banner, and A4 print layout.
3. **Live acquisition-hash integrity paths** — supply correct/wrong/absent `--acquisition-hash` on real images and confirm PASS / ingest-FAIL-rollback / NOT COMPARED behavior end-to-end (the three states are unit-tested at the assemble layer; the live ingest-FAIL interaction is best confirmed manually).

### Gaps Summary

No gaps block the phase goal. All five ROADMAP success criteria and all five declared requirement IDs are verified in the codebase, not merely claimed in SUMMARYs. The Critical (CR-01) and all five Warning (WR-01..05) review findings are confirmed fixed in the actual source, with a dedicated value-level regression test for the CR-01 NULL-meta_addr total-order hole. The full suite (173 tests), ruff, and mypy are green.

Status is `human_needed` (not `passed`) solely because real-image behavior, visual/print appearance, and the live integrity-FAIL path require manual confirmation that the tiny committed fixtures cannot provide. One minor non-blocking item: the implemented fresh-case (A2) guard lacks the automated regression test its plan asserted — recommended as a follow-up, not a blocker.

---

_Verified: 2026-05-31T13:16:37Z_
_Verifier: Claude (gsd-verifier)_
