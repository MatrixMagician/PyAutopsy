---
status: partial
phase: 04-deleted-recovery-known-file-filtering
source: [04-VERIFICATION.md]
started: 2026-05-31T15:09:30Z
updated: 2026-05-31T15:09:30Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. Rendered report shows three distinct, legible sections (Recovered / Orphan / Known-File)
expected: Running `pyautopsy recover <image> --case <dir>` then `pyautopsy analyze <image> --case <dir> --recover --nsrl <nsrl.db> --hash-set-allow <list>` and opening `reports/report.html` shows three separate, clearly-labelled sections — Recovered Files, Orphan Files (orphans NOT mixed into the recovered list, RECOV-02), and Known-File Filtering (noise reduction). The known-file framing is neutral ("known", with source + list name) — no good/bad/safe/malicious verdict language anywhere.
result: [pending]

### 2. Confidence tiers use a glyph/text indicator (not color-only) and per-fs caveats read honestly
expected: Each recovered file's confidence tier (intact vs partial/overwritten) is conveyed with a text/glyph indicator — never color alone — and the per-filesystem caveats (ext4 pointer-zeroing, NTFS resident, FAT first-char-lost) read as honest data-survival statements. No copy anywhere asserts intent (e.g. never "the user deleted this"). A4 print-to-PDF layout has no clipped cards; long hashes/paths wrap.
result: [pending]

## Summary

total: 2
passed: 0
issues: 0
pending: 2
skipped: 0
blocked: 0

## Gaps
