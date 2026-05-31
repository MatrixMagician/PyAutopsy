---
phase: 04-deleted-recovery-known-file-filtering
plan: 00
subsystem: testing
tags: [pytest, fixtures, pytsk3, sqlite3, nsrl, ext4, ntfs, debugfs, tdd-red]

# Dependency graph
requires:
  - phase: 02-filesystem-walk
    provides: committed mkfs/debugfs fixture pattern + ground-truth-constant convention (make_fixtures.py), the run_ingest pipeline, CaseStore.get_files reader, FileRow model
  - phase: 03-timeline-mvp-report
    provides: the WR-02 honesty-test pattern (no intent/good-bad copy) that the recovery honesty stub mirrors
provides:
  - Five deterministic Phase-4 fixtures (ext4 orphan, ext4 overwritten, NTFS resident-deleted, NSRL FILE-variant DB, NSRL METADATA-variant DB) with recorded ground-truth constants
  - Eight named RED test stubs (5 recovery, 3 known-file) pinning the exact 04-VALIDATION.md node IDs
  - Phase-4 conftest fixture accessors for the new images/DBs
affects: [recovery-slice, filtering-slice, integration-slice, "Wave 1 core/recover.py", "Wave 2 filter/nsrl.py + filter/hashsets.py"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Byte-deterministic ext4 fixtures via pinned -U UUID + -E hash_seed + E2FSPROGS_FAKE_TIME (mkfs.ext4 and debugfs)"
    - "Offline NTFS delete by clearing the MFT_RECORD_IN_USE flag (header offset 22) — no offline NTFS-delete CLI exists"
    - "NSRL-format SQLite fixtures (stdlib sqlite3, VACUUM-compacted) storing UPPERCASE hashes to reproduce the case-mismatch trap"
    - "RED Wave-0 stub: import the not-yet-existing module INSIDE the test body so the file collects cleanly but the test fails"

key-files:
  created:
    - tests/test_recover.py
    - tests/test_knownfiles.py
    - tests/fixtures/ext4_orphan.img
    - tests/fixtures/ext4_overwritten.img
    - tests/fixtures/ntfs_resident_deleted.img
    - tests/fixtures/nsrl_minimal.db
    - tests/fixtures/nsrl_metadata.db
  modified:
    - tests/fixtures/make_fixtures.py
    - tests/conftest.py

key-decisions:
  - "ext4 + NSRL fixtures are byte-deterministic; NTFS rebuild is structural-only (mkntfs has no fixed-time/UUID option, no libfaketime on host) — documented honestly, committed-once per the Phase-2 precedent"
  - "ext4 overwritten fixture reflects real ext4 unlink semantics: rm frees/zeroes the victim inode (Pitfall 2), so the surviving forensic signal is the allocated reclaimer owning the victim's former blocks, not a recoverable victim inode"
  - "Offline NTFS deletion via direct MFT in-use-flag byte edit (no ntfscp/ntfs CLI delete exists), preserving the resident $DATA"

patterns-established:
  - "Deterministic ext4 fixtures: _mke2fs_ext4 + _run_debugfs wrap mkfs/debugfs with a frozen clock and pinned UUID/hash_seed"
  - "RED stub honesty scan mirrors Phase-3 WR-02: forbidden intent/good-bad substring set asserted against tier/report copy"

requirements-completed: [RECOV-01, RECOV-02, RECOV-03, FILTER-01]

# Metrics
duration: ~60min
completed: 2026-05-31
---

# Phase 4 Plan 00: Wave-0 Recovery & Known-File Scaffold Summary

**Five deterministic forensic fixtures (orphan/overwritten ext4, resident-deleted NTFS, NSRL FILE+METADATA SQLite DBs with the UPPERCASE-hash trap) plus eight named RED test stubs that pin every RECOV-01/02/03 + FILTER-01 behavior to a currently-failing test.**

## Performance

- **Duration:** ~60 min
- **Completed:** 2026-05-31
- **Tasks:** 2
- **Files modified:** 9 (2 modified, 7 created)

## Accomplishments
- Extended `make_fixtures.py` with four new builders (`build_ext4_orphan_image`, `build_ext4_overwritten_image`, `build_ntfs_resident_deleted_image`, `build_nsrl_fixture`) plus ground-truth constants, all registered in `main()`.
- ext4 + NSRL fixtures verified **byte-deterministic** on rebuild (pinned UUID/hash_seed + frozen clock; stdlib `sqlite3` VACUUM).
- NSRL fixtures store hashes **UPPERCASE** in both a `FILE` table (minimal variant) and a `METADATA` table (modern variant) — reproducing the #1 silent-zero-match trap (Pitfall 4) for the later filtering slice.
- Verified the recovery ground truth live against `pytsk3 20260520`: orphan inode 13 recovers its exact content; NTFS resident-deleted inode 64 recovers its exact resident `$DATA` from the MFT record.
- Eight named RED stubs collect cleanly and fail; the D-14 seam-allowlist gate stays green; no `pytsk3` imported in test files; full suite 173 prior tests still pass.

## Task Commits

1. **Task 1: Extend make_fixtures.py with orphan/overwritten ext4, resident NTFS, NSRL SQLite fixtures** - `76f3cb4` (test)
2. **Task 2: Write failing RED test stubs in test_recover.py / test_knownfiles.py** - `81f7de2` (test)

## Files Created/Modified
- `tests/fixtures/make_fixtures.py` - 4 new deterministic builders + Phase-4 ground-truth constants; deterministic ext4 (`_mke2fs_ext4`/`_run_debugfs`) and offline NTFS delete (`_ntfs_mark_record_deleted`).
- `tests/fixtures/ext4_orphan.img` - file+parent-dir deleted; orphan inode 13, content recoverable (RECOV-02).
- `tests/fixtures/ext4_overwritten.img` - victim deleted, blocks reclaimed by an allocated file (RECOV-03/D-31).
- `tests/fixtures/ntfs_resident_deleted.img` - resident `$DATA` deleted via MFT in-use-flag clear; inode 64 (RECOV-01, Pitfall 3).
- `tests/fixtures/nsrl_minimal.db` / `nsrl_metadata.db` - NSRL-format SQLite, UPPERCASE hashes, `FILE` vs `METADATA` tables (FILTER-01).
- `tests/test_recover.py` - 5 RED stubs (deleted ext4, NTFS resident, orphan-separate, confidence tiers, no-overclaiming honesty).
- `tests/test_knownfiles.py` - 3 RED stubs (NSRL membership uppercase-trap, custom allow/block parse, FILE/METADATA discovery).
- `tests/conftest.py` - Phase-4 fixture accessors for the new images and DBs.

## Decisions Made
- **Determinism scope:** ext4 + NSRL fixtures are byte-reproducible; NTFS is structural-only (committed once). `mkntfs` offers no fixed-UUID/fixed-time option and no `libfaketime` is present on the host, so it embeds wall-clock FILETIMEs and a random volume serial. Brute-force byte normalization corrupted NTFS update-sequence/fixup arrays and was still non-deterministic, so it was rejected in favour of the honest committed-once approach (the Phase-2 NTFS-fixture precedent).
- **Offline NTFS deletion:** no offline NTFS-delete CLI exists (`ntfscp` cannot delete; `ntfsundelete`/`ntfsrm` are recover/mount-only). The fixture marks the file deleted by clearing the `MFT_RECORD_IN_USE` flag (bit 0 at MFT-header offset 22) in-place, leaving the resident `$DATA` intact — exactly the resident-deleted case TSK reads.
- **ext4 overwritten reality:** `debugfs rm` frees the victim inode and the next `write` reuses it (ext4 zeroes the inode on unlink — Pitfall 2). The fixture therefore records the *block-level* overwrite signal (the allocated reclaimer at inode 12 owning the victim's former blocks) rather than a recoverable victim inode; the tier classifier's overwrite/zeroed-pointer paths are unit-tested with fakes per RESEARCH §Pattern 2.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] NTFS fixture build path corrected (no offline delete tool)**
- **Found during:** Task 1
- **Issue:** The plan's `ntfscp`-then-delete approach is not implementable — `ntfscp` has no delete option and no offline NTFS-delete CLI exists, so the build failed.
- **Fix:** Write the resident file with `ntfscp`, then mark it deleted offline by clearing the `MFT_RECORD_IN_USE` flag in its MFT record (`_ntfs_mark_record_deleted`). Resident `$DATA` survives, content recovers byte-exact (verified via pytsk3: inode 64).
- **Files modified:** tests/fixtures/make_fixtures.py
- **Verification:** pytsk3 reopens inode 64 UNALLOC and `read_random` returns the exact `NTFS_RESIDENT_CONTENT`.
- **Committed in:** 76f3cb4

**2. [Rule 1 - Bug] ext4 overwritten ground-truth corrected to real ext4 semantics**
- **Found during:** Task 1
- **Issue:** The plan assumed the deleted victim inode survives with stale pointers overlapping an allocated file. In reality `debugfs rm` frees/zeroes the victim inode and the reclaimer reuses it (ext4 Pitfall 2), so no such surviving deleted inode exists.
- **Fix:** Recorded the honest ground truth — the allocated reclaimer (inode 12) owns the victim's former blocks (`EXT4_OVERWRITTEN_RECLAIMER_META_ADDR`, `EXT4_OVERWRITTEN_VICTIM_INODE_CLEARED`) — and documented the limitation in the builder; the overwrite/zeroed-pointer tier paths are covered by `test_confidence_tiers` with fakes.
- **Files modified:** tests/fixtures/make_fixtures.py
- **Verification:** pytsk3 confirms inode 12 allocated holding RECLAIMED content; no surviving recoverable victim inode.
- **Committed in:** 76f3cb4

**3. [Rule 3 - Blocking] Determinism made achievable for ext4/NSRL; NTFS scoped honestly**
- **Found during:** Task 1
- **Issue:** Default `mkfs.ext4`/`debugfs` embed a random UUID + wall-clock times, so rebuilds were not byte-identical (the determinism acceptance criterion).
- **Fix:** Pin `-U`/`-E hash_seed` and freeze the clock with `E2FSPROGS_FAKE_TIME` (`_mke2fs_ext4`, `_run_debugfs`); NSRL DBs are stdlib-sqlite3 + `VACUUM` (already deterministic). NTFS documented as committed-once structural-only (no tooling to freeze its FILETIMEs).
- **Files modified:** tests/fixtures/make_fixtures.py
- **Verification:** Two consecutive builds of ext4_orphan/ext4_overwritten/nsrl_minimal/nsrl_metadata are sha256-identical.
- **Committed in:** 76f3cb4

---

**Total deviations:** 3 auto-fixed (2 blocking, 1 bug)
**Impact on plan:** All three were necessary to produce buildable, deterministic, forensically-honest fixtures. No scope creep — no production recovery/filtering code was written (correct for Wave 0). The deviations sharpen the ground truth the later waves implement against (notably the ext4-zeroed-pointer and resident-from-MFT honest caveats).

## Issues Encountered
- `sqlite3` CLI is not installed on the host; the acceptance criterion's `sqlite3 ... "SELECT md5"` check was satisfied equivalently via the Python stdlib `sqlite3` module (the fixtures are built with stdlib sqlite3 anyway, no external tool).
- Running the full `make_fixtures.py` regenerates the Phase-2 images too; the Phase-2 images were restored from git after each build so their committed ground truth (asserted by Phase-2 tests, all still passing) is untouched.

## Next Phase Readiness
- **Wave 1 (recovery)** can implement `core/recover.py` + `evidence/filesystem.py` seam extensions test-first against `test_recover.py` and the orphan/resident/overwritten fixtures.
- **Wave 2 (filtering)** can implement `filter/nsrl.py` + `filter/hashsets.py` against `test_knownfiles.py` and the NSRL FILE/METADATA DBs (the UPPERCASE trap is locked in).
- Known limitation carried forward: NTFS fixture is committed-once (not byte-reproducible); the ext4 overwritten fixture exercises block-level overwrite, with inode-zeroed-pointer behavior covered by fakes.

## Known Stubs
The two new test files are intentionally RED Wave-0 stubs (the failing-test foundation). They reference the not-yet-existing `pyautopsy.core.recover`, `pyautopsy.filter.nsrl`, and `pyautopsy.filter.hashsets` and will pass once Waves 1–2 implement those modules. This is the intended Nyquist feedback floor for the phase, not an unresolved defect.

## Self-Check: PASSED

All created files exist on disk; both task commits (`76f3cb4`, `81f7de2`) are present in git history.

---
*Phase: 04-deleted-recovery-known-file-filtering*
*Completed: 2026-05-31*
