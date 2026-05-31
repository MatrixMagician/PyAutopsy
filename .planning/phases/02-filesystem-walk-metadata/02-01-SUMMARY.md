---
phase: 02-filesystem-walk-metadata
plan: 01
subsystem: filesystem-walk
tags: [pytsk3, seam, walk, inventory, ext4, fat32, partitioned, sqlite, typer, forensics, D-14, D-15, D-18, D-20]

# Dependency graph
requires:
  - phase: 02-filesystem-walk-metadata
    plan: 00
    provides: committed ext4/NTFS/FAT32/partitioned fixtures + ground-truth constants, RED META/D-20/read-only stubs, executable D-14 seam allowlist test
  - phase: 01-foundation
    provides: evidence/image.py byte-layer seam (open_image/ImageHandle), CaseStore + transaction(), AuditLog, integrity.assert_source_not_mounted, core/ingest.run_ingest pattern
provides:
  - case schema files + volume_limitations tables (typed cols + JSON attributes; MACB/owner/hash/type interface-first, null until Plans 02-02/03)
  - FileRow + VolumeLimitation frozen dataclasses + CaseStore insert_file/insert_files(bulk)/get_file(s) + insert_volume_limitation/getters
  - evidence/filesystem.py FS-layer native seam (enumerate_volumes/open_fs/walk_fs/FileEntry/FilesystemError) — 2nd D-14 allowlist member
  - FAT_FS_TYPES frozenset[int] pytsk3-free FAT contract (consumed by Plan 02-02 for D-16 local-time handling)
  - core/walk.py run_walk orchestrator (inventory + D-20 limitations + read-only) + WalkResult/WalkError
  - pyautopsy walk CLI subcommand (--case/--timezone/--max-hash-size)
affects: [02-02-macb-ownership, 02-03-hash-filetype]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "FS-layer native seam yields frozen FileEntry value objects (plain types + one read_random closure) so no pytsk3 type escapes the D-14 allowlist"
    - "enumerate_volumes filters to ALLOC partitions (skips volume-system meta table + unallocated gaps) so no empty/garbage walk targets"
    - "bulk insert_files via executemany that still calls _commit_unless_in_transaction so it composes with the orchestrator's outer transaction() (WR-01)"
    - "orchestrator classifies FAT pytsk3-free via the seam's FAT_FS_TYPES contract (D-14 boundary held in core/walk.py)"
    - "D-20: per-volume FS_Info OSError -> VolumeLimitation finding + continue, never abort/garbage (mirrors ingest FAIL-before-propagate)"

key-files:
  created:
    - src/pyautopsy/evidence/filesystem.py
    - src/pyautopsy/core/walk.py
  modified:
    - src/pyautopsy/case/schema.sql
    - src/pyautopsy/case/models.py
    - src/pyautopsy/case/store.py
    - src/pyautopsy/case/__init__.py
    - src/pyautopsy/cli/main.py
    - tests/test_case_store.py
    - tests/test_filesystem.py
    - tests/test_walk.py
    - tests/test_readonly_guarantee.py
    - tests/test_cli_smoke.py

key-decisions:
  - "enumerate_volumes yields only ALLOC partitions (empirically the partitioned fixture also exposes a META partition-table entry + two UNALLOC gaps); walking those would manufacture spurious D-20 rows, so they are skipped"
  - "D-20 test drives the unsupported-volume path with the existing tiny_raw.dd (no recognisable FS -> bare-FS fallback -> FS_Info OSError) instead of adding a fixture; the partitioned fixture's two real partitions both open, so it cannot exercise D-20"
  - "fs_type stored as a stable pytsk3-free label (ext/ntfs/fat/unknown) derived in core/walk.py without importing pytsk3 (D-14)"
  - "FileEntry carries raw epoch MACB ints; UTC/FAT-local normalization deferred to Plan 02-02 so the seam stays free of timezone policy"

patterns-established:
  - "Two-member D-14 native seam allowlist is now an executable reality (image.py + filesystem.py); core/walk.py is pytsk3-free"
  - "Walk orchestrator mirrors ingest orchestrator (transaction + per-stage audit + FAIL-before-propagate + finally close)"

requirements-completed: [META-01]

# Metrics
duration: 18min
completed: 2026-05-31
---

# Phase 2 Plan 01: Wave 1 — First Vertical Walk Slice Summary

**The demonstrable spine of Phase 2: `pyautopsy walk <image> --case ...` enumerates every volume (D-15), walks each supported filesystem read-only, and inventories every entry — including deleted ones (D-18) — as normalized `files` rows with path/size/inode/alloc-status + volume tagging, recording encrypted/unsupported volumes as explicit limitation findings (D-20) behind a pytsk3-free FS seam (D-14).**

## Performance

- **Duration:** ~18 min
- **Completed:** 2026-05-31
- **Tasks:** 3
- **Files created/modified:** 12 (2 created, 10 modified)

## Accomplishments

- **Task 1 — schema + models + store (`fa42039`).** Added `files` and `volume_limitations` tables to `schema.sql` (typed core columns + JSON `attributes` blackboard; MACB/ownership/hash/file-type columns declared interface-first but left null until Plans 02-02/03). Added `FileRow` + `VolumeLimitation` frozen-slots dataclasses, re-exported from `case/__init__.py`, and added `insert_file`/bulk `insert_files` (`executemany`, transaction-composable per WR-01)/`get_file`/`get_files` + `insert_volume_limitation`/getters to `CaseStore`. No raw SQL outside `store.py`.
- **Task 2 — FS-layer native seam (`f64d660`).** Created `evidence/filesystem.py`, the second D-14 allowlist member. `enumerate_volumes` uses `Volume_Info` with a bare-FS `OSError` fallback to offset 0, filtering to ALLOC partitions (byte offset = `part.start * block_size`, Pitfall 7). `open_fs` lets `FS_Info`'s `OSError` propagate for D-20 handling. `walk_fs` does manual `open_dir`/`as_directory` recursion, skips `.`/`..`, guards an inode seen-set, and yields every entry — including deleted (`allocated=False`) and `$OrphanFiles` — as frozen `FileEntry` value objects (plain types + a `read_random` closure; no native type leaks). Exported `FAT_FS_TYPES: frozenset[int]` as the pytsk3-free FAT contract for Plan 02-02.
- **Task 3 — walk orchestrator + CLI (`7c24fb9`).** Created `core/walk.py` mirroring `core/ingest.py`: `run_walk` re-asserts `assert_source_not_mounted` (D-05/P1), opens the existing case store, enumerates volumes, and per volume either records a `VolumeLimitation` on `OSError` (D-20, with an optional LUKS/BitLocker magic-byte hint) and continues, or `walk_fs` → `FileRow` and bulk-inserts inside one `transaction()`. Audits `walk.start`/`walk.volume`/`walk.limitation`/`walk.end` with a FAIL event before any propagation (CR-03). `WalkResult` carries reproducible counts only (P3). `core/walk.py` imports no pytsk3 (D-14) and classifies FAT via `FAT_FS_TYPES`. Added the `pyautopsy walk` Typer command (`--case`/`--timezone` with `ZoneInfo` validation per Security V5/`--max-hash-size`).

## Task Commits

1. **Task 1: files + volume_limitations tables, FileRow/VolumeLimitation models, insert_files** — `fa42039` (feat)
2. **Task 2: evidence/filesystem.py FS-layer native seam (D-14) yielding FileEntry** — `f64d660` (feat)
3. **Task 3: core/walk.py orchestrator + pyautopsy walk CLI** — `7c24fb9` (feat)

## Files Created/Modified

- `src/pyautopsy/evidence/filesystem.py` (new) — FS-layer native seam; `enumerate_volumes`/`open_fs`/`walk_fs`/`FileEntry`/`VolumeEntry`/`FilesystemError`/`FAT_FS_TYPES`.
- `src/pyautopsy/core/walk.py` (new) — `run_walk` orchestrator + `WalkResult`/`WalkError`; pytsk3-free.
- `src/pyautopsy/case/schema.sql` — `files` + `volume_limitations` tables + FK indexes (additive, `IF NOT EXISTS`).
- `src/pyautopsy/case/models.py` — `FileRow` + `VolumeLimitation` dataclasses.
- `src/pyautopsy/case/store.py` — file/limitation insert/get methods + bulk `insert_files` + `_FILES_COLUMNS`/`_file_row_params` helpers.
- `src/pyautopsy/case/__init__.py` — re-export `FileRow`/`VolumeLimitation`.
- `src/pyautopsy/cli/main.py` — `walk` subcommand with timezone validation.
- `tests/test_case_store.py` — FileRow/VolumeLimitation round-trip, bulk-insert, deleted-status, attributes-column tests.
- `tests/test_filesystem.py` — real seam test bodies (volume enumeration, bare-FS fallback, fs-type detection, recursion correctness, deleted-entry, no-native-leak, FAT_FS_TYPES contract).
- `tests/test_walk.py` — real bodies for inventory-includes-deleted, volume-tagging, unsupported-volume-limitation (Wave 2-3 META stubs left RED).
- `tests/test_readonly_guarantee.py` — implemented `test_source_unchanged_after_walk`.
- `tests/test_cli_smoke.py` — `walk` smoke + invalid-timezone + help tests.

## Deviations from Plan

### Auto-fixed / scope adjustments (no architectural change)

**1. [Rule 3 - Blocking] `enumerate_volumes` filters to ALLOC partitions only.**
- **Found during:** Task 2 (empirical probe of `tiny_partitioned.img`).
- **Issue:** `Volume_Info` on the partitioned fixture yields five entries — a `Primary Table (#0)` (META flag), two `Unallocated` gaps (UNALLOC flag), and the two real FAT32/ext4 partitions (ALLOC flag). Yielding the META/UNALLOC entries would either manufacture spurious D-20 limitation rows or attempt to open non-filesystems.
- **Fix:** Skip non-ALLOC partitions in `enumerate_volumes`. The bare-FS fallback path is unaffected. This keeps the inventory honest (plan must-have: "never empty/garbage rows") and yields exactly the two walkable volumes with distinct offsets the D-15 test expects.
- **Files:** `src/pyautopsy/evidence/filesystem.py`.
- **Commit:** `f64d660`.

**2. [Rule 3 - Blocking] D-20 test uses `tiny_raw.dd`, not the partitioned fixture.**
- **Found during:** Task 3.
- **Issue:** The Wave-0 `test_unsupported_volume_records_limitation` stub was signatured on `tiny_partitioned_image`, but both of that image's real partitions open successfully as filesystems, so it cannot exercise the `FS_Info` `OSError` path. The plan's own must-have is verified by an *unsupported* volume.
- **Fix:** Re-signatured the test on the existing `tiny_raw_image` (random bytes, no recognisable filesystem → bare-FS fallback → `FS_Info` `OSError`) — the clean D-20 case — and added a separate `test_volume_tagging_on_partitioned_image` to cover the D-15 multi-volume/offset assertion the original fixture was meant for. No new fixtures were added (Wave 0 owns fixtures).
- **Files:** `tests/test_walk.py`.
- **Commit:** `7c24fb9`.

**3. [Plan note] `iso_utc` not imported into `core/walk.py`.**
- The plan's Task 3 action text suggested importing `from pyautopsy.util.timeutil import iso_utc`, but also explicitly says "leave MACB/uid/gid/mode/hash/type columns null here" — MACB normalization lands in Plan 02-02. Importing an unused symbol would fail the project's `ruff` gate. Omitted; it will be added by Plan 02-02 when it actually normalizes MACB.

The Wave-0 RED stubs were placeholder `pytest.fail` calls; turning them GREEN required writing the real assertion bodies (the plan's TDD-style "turn the RED stubs GREEN"), which is the intended Wave-1 work, not a deviation.

## Authentication Gates

None — no auth surface in a local forensic CLI.

## Known Stubs

The following `files` columns are intentionally declared interface-first and left NULL by this plan, to be populated by later waves (documented in the plan objective and `schema.sql` comments):

| Column(s) | File | Reason | Resolved by |
|-----------|------|--------|-------------|
| `mtime_utc`/`atime_utc`/`ctime_utc`/`crtime_utc`/`timestamp_source` | `files` table | MACB normalization (META-02, D-16) is Wave 2 | Plan 02-02 |
| `uid`/`gid`/`mode` | `files` table | Ownership/mode (META-03) is Wave 2 | Plan 02-02 |
| `md5`/`sha1`/`sha256` | `files` table | Per-file 3-digest hashing (META-04, D-17) is Wave 3 | Plan 02-03 |
| `file_type` | `files` table | Content-signature typing (META-05, D-19) is Wave 3 | Plan 02-03 |

These do not block the plan goal (META-01 full inventory) and are the agreed interface-first design. Their RED test stubs (`test_macb_utc_and_fat_flagged`, `test_no_naive_datetimes`, `test_ownership_and_mode`, `test_three_digest_single_pass`, `test_filetype_by_content_not_extension`) remain RED by design.

## Threat Flags

None — no security-relevant surface was introduced beyond the plan's `<threat_model>`. The walk reads untrusted image input through the existing read-only TSK byte path (no new network/auth/extraction surface), decodes hostile filenames as data only (`errors="replace"`, Security V5), bounds recursion with the inode seen-set (T-2-01-CYCLE), and validates `--timezone` via `ZoneInfo`.

## Verification

- `pytest tests/test_walk.py::test_inventory_includes_deleted_entry tests/test_walk.py::test_unsupported_volume_records_limitation tests/test_walk.py::test_volume_tagging_on_partitioned_image tests/test_readonly_guarantee.py::test_source_unchanged_after_walk tests/test_seam_allowlist.py tests/test_cli_smoke.py` → all green.
- `pytest tests/test_filesystem.py tests/test_case_store.py` → all green.
- Full suite: **140 passed, 5 failed** — the 5 failures are the Wave 2-3 META-02/03/04/05 RED stubs that this plan deliberately leaves RED (baseline before this plan: 122 passed / 12 failed; Wave 1 turned 7 of those 12 GREEN).
- `ruff check` + `mypy` clean on all created/modified source.
- End-to-end: `pyautopsy walk tests/fixtures/tiny_ext4.img --case <dir>` (after `ingest`) exits 0 — "files inventoried: 4, deleted entries: 1, volumes walked: 1, limitations recorded: 0".

## Next Phase Readiness

- The walk shape is fixed: Plans 02-02 (MACB/ownership) and 02-03 (hashes/file-type) enrich the same `FileRow`/`files` columns without changing the walk or the seam.
- `FAT_FS_TYPES` is exported and pytsk3-free, ready for Plan 02-02's D-16 FAT local-time branch; `FileEntry` already carries raw epoch+nano MACB ints and the `read_random` closure those waves need.
- D-14 seam allowlist holds as an executable gate (image.py + filesystem.py only); `core/walk.py` is pytsk3-free.

## Self-Check: PASSED

All created files verified on disk (`evidence/filesystem.py`, `core/walk.py`, this SUMMARY) and all three task commits (`fa42039`, `f64d660`, `7c24fb9`) verified in git history.
