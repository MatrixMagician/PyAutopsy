---
status: partial
phase: 02-filesystem-walk-metadata
source: [02-VERIFICATION.md]
started: 2026-05-31T10:55:00Z
updated: 2026-05-31T10:55:00Z
---

## Current Test

[awaiting human testing on real hardware/data — code paths implemented and wired, but not exercisable by the committed CI fixtures]

## Tests

### 1. Real partitioned multi-FS disk image at scale
expected: On a real partitioned dd/E01 image with multiple supported filesystems, `pyautopsy walk` enumerates every volume via `Volume_Info`, walks each supported FS, and every `files` row carries the correct `volume_id` and byte-offset (`part.start * block_size`). CI only exercises a tiny synthetic partitioned fixture plus bare-FS; large real-world partition tables are not run in CI.
result: [pending]
why_human: Requires a real partitioned multi-filesystem disk image; the committed fixtures are tiny synthetic images. The multi-volume enumeration + offset-tagging code path is implemented and covered by the synthetic `test_volume_tagging_on_partitioned_image`, but at-scale confirmation needs real evidence media. Documented as a Manual-Only verification in 02-VALIDATION.md.

### 2. Sub-second / nano MACB folding
expected: On a real ext4/NTFS image with non-zero `*_nano` timestamp fields, `pyautopsy walk` folds the sub-second values into the row `attributes`, and at least one file carries the sub-second precision.
result: [pending]
why_human: The committed ext4 fixture has `mtime_nano=0` (debugfs does not set nano precision — Assumption A3), so the `*_nano`→`attributes` fold branch has no green automated target. The code path exists and is wired; real images with sub-second timestamps are needed to exercise it. Documented as a Manual-Only verification in 02-VALIDATION.md.

## Summary

total: 2
passed: 0
issues: 0
pending: 2
skipped: 0
blocked: 0

## Gaps
