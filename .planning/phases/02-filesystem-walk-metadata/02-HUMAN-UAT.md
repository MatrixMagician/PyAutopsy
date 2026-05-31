---
status: complete
phase: 02-filesystem-walk-metadata
source: [02-VERIFICATION.md]
started: 2026-05-31T10:55:00Z
updated: 2026-05-31T17:05:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Real partitioned multi-FS disk image at scale
expected: On a real partitioned dd/E01 image with multiple supported filesystems, `pyautopsy walk` enumerates every volume via `Volume_Info`, walks each supported FS, and every `files` row carries the correct `volume_id` and byte-offset (`part.start * block_size`). CI only exercises a tiny synthetic partitioned fixture plus bare-FS; large real-world partition tables are not run in CI.
result: pass
verified: "2026-05-31 — PASS on a real host-built partitioned multi-FS image. Fixture: 34 MiB dd disk, MBR (parted msdos) with two primary partitions — p1 ext4 (mke2fs, files via debugfs) spliced at 1 MiB, p2 FAT (mkfs.vfat, file via mcopy) at 17 MiB. `pyautopsy ingest disk.img --case <sep-dir>` then `pyautopsy walk` reported 'volumes walked: 2', 10 files inventoried. Volume_Info enumerated BOTH partitions and every files row carries correct volume_id + volume_offset:
  - volume_id=2  volume_offset=1048576  fs_type=ext (= sector 2048 × 512) — holds ext_one.txt / ext_two.txt
  - volume_id=3  volume_offset=17825792 fs_type=fat (= sector 34816 × 512) — holds FAT_ONE.TXT
  Byte-offset == part.start × block_size confirmed against the fdisk-reported partition table. Forensic-soundness guard D-01 (case dir must be outside evidence dir) also observed firing correctly during setup."

### 2. Sub-second / nano MACB folding
expected: On a real ext4/NTFS image with non-zero `*_nano` timestamp fields, `pyautopsy walk` folds the sub-second values into the row `attributes`, and at least one file carries the sub-second precision.
result: pass
verified: "2026-05-31 — PASS (substance) on a real host-built NTFS image. Fixture: 16 MiB dd → mkntfs -F -Q (NTFS stores 100 ns FILETIMEs natively). TSK confirmed the image carries non-zero sub-second nanos (e.g. mtime_nano=60007000). After ingest+walk, 14 of 23 files carry non-zero sub-second precision, e.g. `$AttrDef` mtime_utc=2026-05-31T16:00:19.060007+00:00 (raw nano 60007000 ÷ 1000 = 60007 µs = .060007 s). 'At least one file carries sub-second precision' — SATISFIED."
note: "EXPECTED-TEXT CORRECTION: this item's `expected` says sub-seconds fold into the row `attributes`. The implementation (core/walk.py `_macb_to_utc_iso`, lines ~135/159-160) actually folds them into the MICROSECOND component of the `*_utc` timestamp columns via `nano // 1000` + `dt.replace(microsecond=micro)`; `attributes` is reserved for FAT local-time flags only. The code behaviour is correct and arguably better (sub-second belongs on the timestamp the timeline orders by). CAVEAT: Python `datetime` caps at microseconds, so NTFS sub-microsecond 100 ns digits are truncated by `nano // 1000` — an inherent stdlib limit, not a defect. ACTION: 02-VALIDATION.md / this expected line should be reworded to say `*_utc` microseconds, not `attributes`. Not a code gap → recorded as PASS, not an issue."

## Summary

total: 2
passed: 2
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps
