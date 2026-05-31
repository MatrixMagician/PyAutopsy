---
phase: 04-deleted-recovery-known-file-filtering
plan: 04
subsystem: evidence-seam / deleted-recovery
tags: [RECOV-02, gap-closure, tdd, forensic-soundness, fat32, ext4]
requires:
  - "src/pyautopsy/evidence/filesystem.py:walk_fs (root-inode tagging)"
provides:
  - "Root-level deleted files classify is_orphan=False (Recovered), not Orphan"
  - "None reserved exclusively for the pass-2 range-scan orphan (no surviving dir link)"
  - "Committed FAT root-deletion regression fixture (determinism gate now catches a revert)"
affects:
  - "core/recover.py orphan/recovered split (driven by DeletedInode.is_orphan)"
  - "report Recovered Files / Orphan Files sections"
tech-stack:
  added: []
  patterns:
    - "Effective-parent resolution at the top of walk_fs (root call substitutes fs.info.root_inum)"
    - "FAT root-deletion fixture via mcopy + mdel (mtools), committed (non-byte-deterministic, structure+ground-truth reproduce)"
key-files:
  created: []
  modified:
    - "src/pyautopsy/evidence/filesystem.py"
    - "tests/fixtures/fake_fs.py"
    - "tests/fixtures/make_fixtures.py"
    - "tests/fixtures/tiny_fat32.img"
    - "tests/test_filesystem.py"
    - "tests/test_recover.py"
decisions:
  - "Fix lives entirely in walk_fs (tag root entries with fs.info.root_inum); iter_deleted_inodes needs no change because the root inode is already in allocated_inodes on FAT/ext4 (verified) — no narrow guard required."
  - "FAT root deletion matched by recorded inode (FAT_DELETED_META_ADDR=4), not name, because FAT loses the first char of a deleted name (Pitfall 3)."
  - "Only tiny_fat32.img regenerated/committed; the other regenerated images (ext4/ntfs/partitioned) were restored to avoid non-deterministic-builder churn unrelated to this fix."
metrics:
  duration: "~25 min"
  completed: "2026-05-31"
  tasks: 2
  files_changed: 6
---

# Phase 4 Plan 04: Root-Level Deleted-File Misclassification Fix Summary

Root-level deleted files now classify `is_orphan=False` (Recovered) by tagging `walk_fs` root entries with the filesystem root inode (`fs.info.root_inum`) — `None` is reserved exclusively for genuine no-dir-link range-scan orphans (RECOV-02).

## What Changed

**Root cause (from 04-HUMAN-UAT diagnosis):** `walk_fs()` yielded root-level entries with `parent_addr=None`, and `iter_deleted_inodes()` computed `parent_known_orphan = (parent_addr is None or parent_addr not in alloc_inodes)`. `None` was overloaded — meaning BOTH "root-level entry" (walk default) AND "no surviving dir link" (the deliberate pass-2 orphan). Since the root directory is always allocated, a root-level deletion is NOT an orphan, yet every one was flagged orphan, emptying the report's Recovered Files section and dumping root deletions into Orphan Files with the false "parent directory is itself gone" provenance claim (overclaim, against D-32).

**Task 1 (fix + RED):** In `walk_fs`, resolved the effective parent address once at the top of the function: the genuine root call (`_depth == 0 and parent_addr is None`) substitutes `int(fs.info.root_inum)`; the recursive call is unchanged (it already passes the child directory's own non-None `meta_addr`), so the guard fires only for the top-level invocation. `iter_deleted_inodes` needed no change — the root inode is already in `allocated_inodes(fs)` on FAT and ext4 (verified: `root_inum=2`, in-alloc on all supported fixtures), so the existing `parent_known_orphan` test becomes correct automatically. Extended `_FakeFSInfo`/`FakeFS` to expose `root_inum`/`first_inum`/`last_inum` for the WR-03/WR-04 unit tests.

**Task 2 (regression fixtures + tests):** Added a committed FAT root-deletion fixture (`build_tiny_fat32_image` now writes a second root file via `mcopy` then deletes it via `mdel`; regenerated and committed `tiny_fat32.img`). New constants `FAT_DELETED_NAME/CONTENT/META_ADDR` and `EXT4_DELETED_META_ADDR`. Added regression tests pinning BOTH directions for BOTH filesystems: a root deletion (ext4 `deleted.txt` + the FAT root deletion) classifies `is_orphan=False` / lands in `result.recovered`; a removed-parent deletion (`ext4_orphan` fixture) still classifies `is_orphan=True` / lands in `result.orphans`. Corrected the two now-stale assertions (`test_root_entries_have_no_parent_addr` → `test_root_entries_carry_root_inode_parent_addr`; the root branch of `test_parent_addr_threaded_through_recursion`) that encoded the old None-at-root contract.

## Verification

- `grep -n root_inum src/pyautopsy/evidence/filesystem.py` shows the root-inode tagging (None overload removed for the walk path).
- Genuine pass-2 range-scan orphan path (`DeletedInode(... parent_addr=None, is_orphan=True ...)` at filesystem.py:524) unchanged.
- `tests/test_seam_allowlist.py` passes — D-14 holds, no new pytsk3 importer (all native access stays inside the seam).
- `tests/test_reproducibility.py` passes — report bodies remain byte-deterministic (CLI-02).
- Full regression sweep: `tests/test_filesystem.py tests/test_recover.py tests/test_seam_allowlist.py tests/test_reproducibility.py` → 26 passed.
- Full suite: 188 passed. ruff + mypy clean on changed source.

## Threat Model Mitigations

- **T-04-04-OVERCLAIM (mitigated):** Root deletions no longer carry the false "parent directory is itself gone" claim; orphan-ness now derives from the allocated root inode + the genuine TSK ORPHAN flag. Pinned by `test_root_level_deletion_is_not_orphan` + `test_root_deletion_reported_as_recovered_not_orphan`.
- **T-04-04-UNDERCLAIM (mitigated):** The fix does NOT swallow genuine orphans — `test_removed_parent_deletion_is_still_orphan` and the preserved `test_orphan_reported_separately` pin that the `ext4_orphan` removed-parent deletion stays `is_orphan=True`.
- **T-04-04-RO (accepted):** All access stays read-only via pytsk3 over the read-only image; the fix only changes an in-memory `parent_addr` value, never writes the source.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixture regeneration perturbed non-deterministic sibling images**
- **Found during:** Task 2 (running `python tests/fixtures/make_fixtures.py`)
- **Issue:** The full builder regenerated `tiny_ext4.img`, `tiny_ntfs.img`, `tiny_partitioned.img`, and `ntfs_resident_deleted.img` — these Phase-2/NTFS builders are not byte-deterministic (no `E2FSPROGS_FAKE_TIME` pinning on the plain Phase-2 ext4/partitioned builders; mkntfs embeds wall-clock FILETIMEs), so they showed as modified despite no semantic change.
- **Fix:** Restored those four images via `git checkout --`; committed only `tiny_fat32.img` (the sole image with an intentional content change). Determinism of report bodies (the actual CLI-02 gate) is unaffected — `test_reproducibility.py` stays green.
- **Files modified:** committed only `tests/fixtures/tiny_fat32.img`.
- **Commit:** a15c464

**2. [Rule 1 - Bug] FakeFS sub-dir inode collided with default root_inum**
- **Found during:** Task 2 (correcting `test_parent_addr_threaded_through_recursion`)
- **Issue:** The original fake used `sub` inode addr=2, which now equals the default `root_inum=2`, making the `child.parent_addr == sub.meta_addr` assertion ambiguous against the root tag.
- **Fix:** Moved the fake sub/child inodes to 10/11 so the root inode (2) and the sub inode (10) are distinct, keeping the assertion meaningful.
- **Files modified:** tests/test_filesystem.py
- **Commit:** a15c464

## TDD Gate Compliance

RED → GREEN → (no refactor) gate satisfied:
- RED: `63123a0` test(04-04) — failing root-level-deletion non-orphan regression.
- GREEN: `a84844f` fix(04-04) — root-inode tagging in walk_fs.
- Additional regression pinning + stale-assertion correction: `a15c464` test(04-04).

## Self-Check: PASSED

- `src/pyautopsy/evidence/filesystem.py` — FOUND (root_inum tagging present)
- `tests/fixtures/tiny_fat32.img` — FOUND (regenerated with root deletion, inode 4)
- Commit `63123a0` — FOUND
- Commit `a84844f` — FOUND
- Commit `a15c464` — FOUND
