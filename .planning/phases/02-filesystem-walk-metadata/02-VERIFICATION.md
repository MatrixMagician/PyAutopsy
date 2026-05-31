---
phase: 02-filesystem-walk-metadata
verified: 2026-05-31T11:32:38Z
status: passed
score: 5/5 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: human_needed
  previous_score: 5/5 must-haves verified
  note: "2026-05-31 — both human-verification items confirmed PASS on host-built fixtures (see 02-HUMAN-UAT.md). Status advanced human_needed -> passed."
human_verification:
  - test: "Walk a real partitioned multi-FS disk image (E01/dd) at scale and confirm every volume's rows carry the correct volume_id and byte-offset"
    expected: "Each partition's files are tagged with a distinct, correct volume_id/volume_offset; no volume is silently dropped or mis-offset"
    why_human: "CI only exercises a tiny synthetic partitioned fixture + bare-FS; large real-world partition tables (extended partitions, GPT, LVM) are not represented in the committed fixtures (02-VALIDATION Manual-Only row 1)"
    result: pass
    verified_via: "2026-05-31 host-built MBR disk (parted) with ext4 @1 MiB + FAT @17 MiB; pyautopsy walk reported 2 volumes; files rows carry volume_id=2 off=1048576 (ext) and volume_id=3 off=17825792 (fat), == part.start x block_size. See 02-HUMAN-UAT.md test 1."
  - test: "Walk a real ext4/NTFS image whose files have non-zero sub-second MACB (*_nano) timestamps and confirm the sub-second values are folded into the *_utc timestamp microseconds"
    expected: "At least one file row carries the sub-second component in its *_utc columns; the nano-fold code branch executes against real data"
    why_human: "The committed ext4 fixture has mtime_nano=0 (debugfs does not set it, Assumption A3), so the *_nano->*_utc-microsecond fold branch has no green automated target (02-VALIDATION Manual-Only row 2). Code path is implemented but not exercised by committed fixtures."
    result: pass
    verified_via: "2026-05-31 host-built mkntfs image (NTFS 100ns FILETIMEs); 14/23 files carry non-zero sub-second, e.g. mtime_utc=...T16:00:19.060007+00:00 from raw nano 60007000. NOTE: sub-seconds fold into the *_utc microsecond component (nano // 1000), NOT into attributes (which holds FAT local-time flags only) — corrects the original wording. See 02-HUMAN-UAT.md test 2 + memory e158e52b."
---

# Phase 2: Filesystem Walk & Metadata Verification Report

**Phase Goal:** An examiner gets a complete, normalized inventory of every file on supported filesystems (ext4/NTFS/FAT) with UTC-correct MACB timestamps, ownership/perms, and per-file hashes — the second source-of-truth that feeds the timeline. Encrypted/unsupported volumes are reported as explicit known-limitation findings; file type is identified by content signature, not extension.
**Verified:** 2026-05-31T11:32:38Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth (ROADMAP Success Criterion) | Status | Evidence |
|---|-----------------------------------|--------|----------|
| 1 | Walks ext4/NTFS/FAT and inventories every file (path, size, inode/MFT addr, alloc/unalloc status) as normalized rows incl. deleted entries; multi-volume tagging + bare-FS fallback (META-01, D-15, D-18) | ✓ VERIFIED | `evidence/filesystem.py` `enumerate_volumes`/`walk_fs`/`FileEntry` (pytsk3-confined); `core/walk.py` `run_walk`→`FileRow`; `test_inventory_includes_deleted_entry`, `test_volume_enumeration`, `test_volume_tagging_on_partitioned_image` all PASS. Deleted entry asserted `allocated=False` w/ populated `meta_addr`. |
| 2 | MACB stored tz-aware UTC ISO-8601 (+00:00); no naive datetimes; timestamp_source per fs-type; FAT local-time rebased to UTC; zero→None (META-02, D-16, D-10) | ✓ VERIFIED | `_macb_to_utc_iso` in `walk.py`; every value routed through `iso_utc` (rejects naive); runtime check: FAT NY wall-clock `secs=1700000000` persists shifted +5h (03:13:20Z) vs UTC interp (22:13:20Z) — CR-01 fix holds; zero→None confirmed. `test_macb_utc_and_fat_flagged`, `test_no_naive_datetimes`, `test_macb_to_utc_iso_fat_reinterprets_local` PASS w/ value-level CR-01 regression guard. |
| 3 | Ownership UID/GID + permission/mode bits recorded per file (META-03) | ✓ VERIFIED | `_build_file_row` populates `uid`/`gid`/`mode` from seam plain ints; meta-less→None preserved. `test_ownership_and_mode` PASS. |
| 4 | MD5+SHA-1+SHA-256 single streaming pass; empty-file sentinels; --max-hash-size honored; read errors degrade gracefully (META-04, D-17) | ✓ VERIFIED | `integrity.hash_file` — one loop, three hashers; `EMPTY` sentinels (d41d8cd9.../da39a3ee.../e3b0c442...); `max_size` skip; short-read→None; WR-01 per-entry OSError guard in `walk.py` (`read_error` reason, walk continues). `test_three_digest_single_pass` PASS. |
| 5 | File type by content signature not extension; encrypted/unsupported volume → explicit known-limitation finding, walk continues, no garbage rows (META-05, D-19, D-20) | ✓ VERIFIED | `filetype.py` `magic.from_buffer(mime=True)` w/ `hasattr(magic,"from_buffer")` binding guard; `test_filetype_by_content_not_extension` PASS (text file w/ misleading ext→text/plain). D-20: `run_walk` per-volume `except OSError`→`insert_volume_limitation`+continue; `test_unsupported_volume_records_limitation` PASS. |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/pyautopsy/evidence/filesystem.py` | FS-layer native seam (enumerate_volumes/open_fs/walk_fs/FileEntry/FAT_FS_TYPES) | ✓ VERIFIED | Exports `FAT_FS_TYPES={2,4,8}`, `EXT_FS_TYPES={128,256,8192}`, `NTFS_FS_TYPES={1}` (CR-02 corrected enums); parent_addr threaded (WR-03); depth cap (WR-04) |
| `src/pyautopsy/core/walk.py` | run_walk inventory + MACB/owner/hash/type + D-20 | ✓ VERIFIED | pytsk3-free (0 imports); MACB/owner/hash/type all populated; FAIL-before-propagate audit |
| `src/pyautopsy/evidence/integrity.py` | hash_file 3-digest single pass + sentinels | ✓ VERIFIED | `hash_file` present, sha1 added, EMPTY sentinel; 0 pytsk3 imports |
| `src/pyautopsy/evidence/filetype.py` | python-magic wrapper + binding guard | ✓ VERIFIED | `hasattr(magic,"from_buffer")` guard, NOT file-magic; 0 pytsk3 imports |
| `src/pyautopsy/case/schema.sql` | files + volume_limitations tables | ✓ VERIFIED | Both tables present; `volume_id`/`volume_offset NOT NULL` on files (WR-06 fix) |
| `tests/test_seam_allowlist.py` | executable D-14 gate | ✓ VERIFIED | Passing executable test (2 passed); not a convention |
| `pyproject.toml` | python-magic==0.4.27 | ✓ VERIFIED | Declared in [project.dependencies] |

### Key Link Verification

| From | To | Via | Status |
|------|----|----|--------|
| `core/walk.py` | `evidence/filesystem.py` | `fs_seam.enumerate_volumes/open_fs/walk_fs` | ✓ WIRED |
| `core/walk.py` | `case/store.py` | `insert_files` in `transaction()` | ✓ WIRED |
| `core/walk.py` | `util/timeutil.iso_utc` + `from_epoch_utc` | every MACB value | ✓ WIRED |
| `core/walk.py` | `evidence/integrity.hash_file` | over read_random closure | ✓ WIRED |
| `core/walk.py` | `evidence/filetype.file_type` | over read_random closure | ✓ WIRED |
| `cli/main.py` | `core/walk.run_walk` | walk command + --timezone (ZoneInfo) + --max-hash-size | ✓ WIRED |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| FAT local-time rebasing actually shifts (CR-01) | `_macb_to_utc_iso(1700000000,0,is_fat=True,walk_tz=NY)` | `2023-11-15T03:13:20+00:00` vs UTC `22:13:20` (shifted +5h) | ✓ PASS |
| zero epoch → None | `_macb_to_utc_iso(0,...)` | `None` | ✓ PASS |
| Correct fs-type enums (CR-02) | import FAT/EXT/NTFS frozensets | FAT{2,4,8} EXT{128,256,8192} NTFS{1} | ✓ PASS |
| pytsk3 confined to allowlist | grep src/ | only image.py + filesystem.py | ✓ PASS |
| Per-requirement node tests | pytest 9 META/D-20/RO nodes | 9 passed | ✓ PASS |

### Probe Execution

No `scripts/*/tests/probe-*.sh` probes declared for this phase; verification driven by the pytest suite (the phase's declared validation mechanism per 02-VALIDATION.md).

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| META-01 | 02-00, 02-01 | Inventory every file (path/size/inode/alloc status) ext4/NTFS/FAT | ✓ SATISFIED | walk_fs + run_walk; deleted+volume-tag tests pass |
| META-02 | 02-02 | MACB normalized UTC + tz + timestamp_source | ✓ SATISFIED | _macb_to_utc_iso + iso_utc invariant; CR-01 fix verified |
| META-03 | 02-02 | UID/GID + mode per file | ✓ SATISFIED | _build_file_row uid/gid/mode; test_ownership_and_mode |
| META-04 | 02-03 | MD5+SHA-1+SHA-256 single pass during walk | ✓ SATISFIED | integrity.hash_file; test_three_digest_single_pass |
| META-05 | 02-03 | File type by content signature | ✓ SATISFIED | filetype.file_type; test_filetype_by_content_not_extension |

All 5 declared requirement IDs (META-01..05) map to passing implementation. No orphaned requirements — REQUIREMENTS.md maps exactly META-01..05 to Phase 2, all claimed across plans 02-00/01/02/03.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none) | — | No unreferenced TBD/FIXME/XXX debt markers in phase-modified source | — | Clean |

All Known-Stub columns from Plan 02-01 (MACB/owner/hash/type left null interface-first) were subsequently populated by Plans 02-02/02-03 — verified no longer null. No `return null`/empty-stub render paths. The single grep hit for "pytsk3" in walk.py is a docstring sentence, not an import (confirmed by `grep -Ec '^\s*(import|from)\s+pytsk3'` = 0).

### Code-Review Closure (02-REVIEW.md status: resolved)

| Finding | Severity | Fix verified in code | Commit |
|---------|----------|----------------------|--------|
| CR-01 FAT rebasing no-op | Critical | FAT branch reinterprets wall-clock in walk_tz; value-shift confirmed at runtime + regression-guard test | 7db73c9 |
| CR-02 ext2/3 enum mislabel | Critical | EXT_FS_TYPES={128,256,8192} from seam; NTFS_FS_TYPES added | 7db73c9 |
| WR-01 single bad read aborts walk | Warning | per-entry OSError guard → read_error, continue | 530b055 |
| WR-02 unalloc typing no caveat | Warning | file_type_provenance="unallocated-blocks-may-be-reused" | 530b055 |
| WR-03 parent_addr always None | Warning | parent inode threaded through recursion | 8956bbc |
| WR-04 recursion depth | Warning | _MAX_WALK_DEPTH cap | 8956bbc |
| WR-05 broad except | Warning | narrowed to operational set | 7581425 |
| WR-06 volume_id nullable vs non-opt | Warning | columns NOT NULL | 40c3ffc |
| IN-01/02/04 | Info | doc accuracy + epoch guard | ef34062 |

### Quality Gates

- `python3 -m pytest -q` → **155 passed** (matches expected count incl. the review-fix regression tests).
- `ruff check src tests` → All checks passed.
- `mypy src` → No issues found.
- `tests/test_seam_allowlist.py` → 2 passed (D-14 executable gate green).

### Human Verification — COMPLETE (2026-05-31)

Both items have now been confirmed PASS on host-built fixtures (full evidence in `02-HUMAN-UAT.md`). The code paths were implemented all along; they simply had no green automated target with the committed fixtures.

1. **Real partitioned multi-FS disk at scale** — ✅ PASS. Host-built MBR disk (ext4 @1 MiB + FAT @17 MiB); `pyautopsy walk` enumerated 2 volumes; every `files` row carries the correct `volume_id`/byte-offset (`volume_id=2 off=1048576` ext, `volume_id=3 off=17825792` fat, each == `part.start × block_size`).
2. **Sub-second / nano MACB folding** — ✅ PASS. Host-built `mkntfs` image (NTFS 100 ns FILETIMEs); 14/23 files carry non-zero sub-second precision, e.g. `mtime_utc=…T16:00:19.060007+00:00`. NOTE: sub-seconds fold into the **`*_utc` microsecond component** (`nano // 1000`), **not** into `attributes` — the original wording is corrected here and in 02-VALIDATION.md.

### Gaps Summary

No gaps. All 5 ROADMAP success criteria and all 5 requirement IDs (META-01..05) are observably satisfied in the codebase. The two prior Critical code-review findings (CR-01 FAT no-op, CR-02 ext enum mislabel) are confirmed fixed with both source-level and value-level (regression-guarding) evidence; all Warning/Info findings are closed. The D-14 native-seam allowlist is an executable, passing gate with pytsk3 confined to image.py + filesystem.py. The read-only guarantee holds across the full walk. The full suite is 155 green, ruff + mypy clean.

Status is now `passed`: the two behaviors that were intrinsically un-automatable with the committed fixtures (large real partition tables; non-zero sub-second MACB) have since been verified on host-built fixtures on 2026-05-31 (see 02-HUMAN-UAT.md). The automated surface remains fully green.

---

_Verified: 2026-05-31T11:32:38Z_
_Verifier: Claude (gsd-verifier)_
_Human items resolved: 2026-05-31 (host-built fixtures; see 02-HUMAN-UAT.md)_
