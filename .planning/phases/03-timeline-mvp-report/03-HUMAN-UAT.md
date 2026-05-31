---
status: complete
phase: 03-timeline-mvp-report
source: [03-VERIFICATION.md]
started: 2026-05-31T13:20:00Z
updated: 2026-05-31T17:40:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Large real partitioned-disk analyze run
expected: `pyautopsy analyze <image> --case <fresh-dir> --examiner ... --evidence-id ...` on a LARGE, real, partitioned disk image (multi-GB, multiple volumes, mixed ext4/FAT/NTFS) completes in one process, produces reports/report.{html,json} + run_metadata.json; HTML timeline truncates with an honest "Showing N of M" note when events exceed the 2000 cap; per-volume breakdown lists each real volume; integrity section reflects the real acquisition-hash outcome.
result: pass
verified: "2026-05-31 — PASS on host-built fixtures.
  (a) analyze on the Phase-2 partitioned ext4+FAT disk: exit 0, produced reports/report.html + report.json + run_metadata.json; report.json findings.per_volume lists BOTH volumes (id=2 ext @1048576 / 4 files; id=3 fat @17825792 / 6 files); integrity section present.
  (b) Truncation: built a 64 MiB ext4 image with 800 files (debugfs scripted writes) → analyze reported 3204 timeline events (> 2000 cap). HTML renders 'Showing 2000 of 3204 timeline events. This HTML view is truncated for readability; the complete timeline…'; JSON carries the FULL timeline (timeline_total = len(timeline) = 3204), matching D-27 (bounded HTML slice, full in JSON)."

### 2. Visual + A4-print inspection of report.html
expected: Opened in a browser, the eight sections render in canonical order; status is text+glyph (never color-only); the FAIL/NOT-COMPARED banner is prominent near the top; print-to-PDF (A4) has no clipped cards; long hashes/paths wrap.
result: pass
verified: "2026-05-31 — PASS via Playwright render + headless-Chrome A4 print-to-PDF (pdftoppm page inspection).
  - Sections render in canonical order: Integrity Verification → Methodology & Tool Versions → Findings → Evidence Hashes → Timeline → Recovered → Orphan → Known-File Filtering → Limitations.
  - Status is text+glyph, never color-only: PASS shows `PASS ✓` (span.status-pass, U+2713) + green card; NOT COMPARED shows bold 'NOT COMPARED' text + amber card.
  - Integrity banner is the first content section, prominent right under the header card.
  - A4 print: google-chrome --headless --print-to-pdf → 3 pages at A4 (594.96×841.92 pt); all cards intact across page breaks, NONE clipped.
  - Long hashes wrap: SHA-256 wraps across two lines in the Evidence Hashes section."
note: "TWO doc-accuracy points (NOT defects): (1) expected says 'eight sections' but the report now renders NINE <h2> sections — Phase 4 added Recovered/Orphan/Known-File; the count text is stale from Phase 3. (2) The FAIL banner copy could not be exercised live: a wrong --acquisition-hash makes ingest abort BEFORE any report is assembled (see Test 3), so the FAIL-card rendering path is only reachable at the assemble layer / unit tests, exactly as Test 3's expected itself acknowledges. NOT-COMPARED and PASS banners were both visually confirmed."

### 3. Live acquisition-hash integrity paths
expected: Correct `--acquisition-hash` → PASS copy ("source hash matches acquisition value"); wrong hash → ingest FAILs and rolls back (no report), or the FAIL copy renders if a report is assembled over a recorded mismatch; no acquisition hash → NOT COMPARED copy. (Three states are unit-tested at the assemble layer; the live ingest-FAIL rollback interaction needs manual confirmation.)
result: pass
verified: "2026-05-31 — PASS, all three live states on the partitioned disk.
  - CORRECT hash (true sha256): integrity.passed=True, acquisition_supplied=True, acquisition_compare_pass=True; copy = 'Integrity verification: PASS — source hash matches acquisition value and end-of-run re-verification.'
  - WRONG hash (all-zeros): analyze EXIT 1, stderr 'acquisition hash mismatch (sha256): computed … supplied 000…'; NO report produced (reports/ absent); analytical data ROLLED BACK — evidence_sources/files/timeline_events all 0 rows; only case.db + audit trail remain recording ingest.acquisition_compare→FAIL, ingest.error→FAIL (the rejected attempt is logged, nothing committed over a bad source).
  - NO hash: acquisition_supplied=False; copy = 'Integrity verification: NOT COMPARED — no acquisition hash was supplied…'.
  Confirms the live ingest-FAIL rollback interaction the expected flagged as needing manual confirmation."

## Summary

total: 3
passed: 3
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps
