---
status: partial
phase: 03-timeline-mvp-report
source: [03-VERIFICATION.md]
started: 2026-05-31T13:20:00Z
updated: 2026-05-31T13:20:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. Large real partitioned-disk analyze run
expected: `pyautopsy analyze <image> --case <fresh-dir> --examiner ... --evidence-id ...` on a LARGE, real, partitioned disk image (multi-GB, multiple volumes, mixed ext4/FAT/NTFS) completes in one process, produces reports/report.{html,json} + run_metadata.json; HTML timeline truncates with an honest "Showing N of M" note when events exceed the 2000 cap; per-volume breakdown lists each real volume; integrity section reflects the real acquisition-hash outcome.
result: [pending]

### 2. Visual + A4-print inspection of report.html
expected: Opened in a browser, the eight sections render in canonical order; status is text+glyph (never color-only); the FAIL/NOT-COMPARED banner is prominent near the top; print-to-PDF (A4) has no clipped cards; long hashes/paths wrap.
result: [pending]

### 3. Live acquisition-hash integrity paths
expected: Correct `--acquisition-hash` → PASS copy ("source hash matches acquisition value"); wrong hash → ingest FAILs and rolls back (no report), or the FAIL copy renders if a report is assembled over a recorded mismatch; no acquisition hash → NOT COMPARED copy. (Three states are unit-tested at the assemble layer; the live ingest-FAIL rollback interaction needs manual confirmation.)
result: [pending]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps
