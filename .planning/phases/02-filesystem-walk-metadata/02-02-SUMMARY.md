---
phase: 02-filesystem-walk-metadata
plan: 02
subsystem: filesystem-walk
tags: [macb, timestamps, utc, fat, local-time, ownership, mode, forensics, D-10, D-16, META-02, META-03, walk]

# Dependency graph
requires:
  - phase: 02-filesystem-walk-metadata
    plan: 01
    provides: core/walk.py run_walk orchestrator + _build_file_row + FAT_FS_TYPES pytsk3-free contract + FileRow MACB/owner columns (null) + fs_ftype on FileEntry
  - phase: 02-filesystem-walk-metadata
    plan: 00
    provides: committed ext4/NTFS/FAT32 fixtures + Plan-00 ground-truth uid/gid constants + RED META-02/03 stubs
  - phase: 01-foundation
    provides: util/timeutil.iso_utc (rejects naive) + from_epoch_utc; CaseStore JSON-attributes round-trip
provides:
  - MACB normalization in core/walk.py (zero->None, FAT local-time rebase via ZoneInfo + flag, ext4/NTFS UTC, nano-fold) routed through iso_utc
  - timestamp_source provenance per fs-type (ext4:inode / ntfs:$STANDARD_INFORMATION / fat:dir-entry)
  - uid/gid/mode persisted per file (META-03) from the seam's plain-int fields; None preserved for meta-less entries
affects: [02-03-hash-filetype, 03-timeline]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Every MACB value routed through iso_utc (raises on naive) so a naive/local timestamp is structurally impossible to persist (D-10, threat T-2-02-NAIVE)"
    - "FAT epochs interpreted as wall-clock in walk_tz=ZoneInfo(--timezone) then converted to UTC + flagged local-time-inferred/assumed_timezone (D-16, threat T-2-02-FAT)"
    - "Zero TSK epoch -> None (never fake 1970-01-01); meta-less entries keep null MACB + null ownership (never coerced to 0)"
    - "walk.py stays pytsk3-free: FAT classified via the seam's FAT_FS_TYPES frozenset[int] (D-14 boundary held)"

key-files:
  created: []
  modified:
    - src/pyautopsy/core/walk.py
    - tests/test_walk.py

key-decisions:
  - "ZoneInfo(timezone) resolved once at run_walk entry so a bad --timezone raises before any evidence access (threat T-2-02-TZ / Security V5)"
  - "timestamp_source derived from the pytsk3-free fs-type label (ext->ext4:inode, ntfs->ntfs:$STANDARD_INFORMATION, fat->fat:dir-entry); exact strings asserted across all three fixtures"
  - "test_ownership_and_mode asserts uid/gid against the exact Plan-00 constants but mode against round-trip non-null int, because debugfs 'sif mode 644' stores 644 DECIMAL (TSK reports 644), which differs from the EXT4_FILE_MODE=0o644 constant — asserting the constant would be wrong; the honest invariant is exact uid/gid + non-null integer mode that survives persistence"
  - "uid/gid/mode wired in _build_file_row alongside MACB (single per-entry mapping point); meta-less entries inherit FileEntry's None"

# Metrics
metrics:
  duration: ~10m
  completed: 2026-05-31
  tasks: 2
  files-changed: 2
---

# Phase 2 Plan 2: MACB Time + Ownership/Mode Enrichment Summary

MACB timestamps are now normalized to tz-aware UTC ISO-8601 with explicit +00:00 offset (FAT rebased from local time via the `--timezone` zone and flagged `local-time-inferred`, zero epochs → `None`, every value forced through `iso_utc` so naive datetimes are structurally impossible), and each file row carries UID/GID/mode plus a per-fs-type `timestamp_source` — all without `core/walk.py` ever importing pytsk3.

## What was built

- **`_macb_to_utc_iso(secs, nano, *, is_fat, walk_tz)`** — the single MACB normalizer. `0` epoch → `None` (Pitfall 3, never 1970); FAT path interprets the integer as wall-clock in `walk_tz` then converts aware→UTC; ext4/NTFS path uses `from_epoch_utc`; sub-second `nano` folded onto the datetime when present. Every return routed through `iso_utc`, which raises on naive datetimes (T-2-02-NAIVE mitigation).
- **`_macb_fields(entry, walk_tz)`** — maps one `FileEntry` to its `{m,a,c,b}` columns, the exact `timestamp_source` provenance string, and FAT-only `attributes` (`time_precision=local-time-inferred`, `assumed_timezone=str(walk_tz)`). Meta-less entries (`meta_addr is None`) get null MACB and no provenance.
- **`_build_file_row`** — now also populates `mtime_utc/atime_utc/ctime_utc/crtime_utc`, `timestamp_source`, `attributes`, and `uid/gid/mode` (META-03) from the seam's plain-int fields; `None` preserved for meta-less entries.
- **`run_walk`** — resolves `walk_tz = ZoneInfo(timezone)` once up front (bad zone raises before evidence access, T-2-02-TZ) and threads it into the per-entry row build.
- **Tests** — replaced the three placeholder `pytest.fail` stubs with real assertions across the ext4/NTFS/FAT32 fixtures: UTC `+00:00` offsets, exact `timestamp_source` strings, FAT local-time flag + `assumed_timezone`, FAT `ctime==0 → None`, the no-naive re-parse invariant, and exact uid/gid + non-null integer mode with meta-less→None.

## Tasks

| Task | Name | Commits | Files |
| ---- | ---- | ------- | ----- |
| 1 | MACB → tz-aware UTC ISO-8601, FAT local-time handling, zero→None | b5a092b (RED), 6f1fe01 (GREEN) | tests/test_walk.py, src/pyautopsy/core/walk.py |
| 2 | UID/GID + permission/mode bits per file | 22b0694 (RED), 3255332 (GREEN) | tests/test_walk.py, src/pyautopsy/core/walk.py |

## Verification

- `pytest tests/test_walk.py::test_macb_utc_and_fat_flagged tests/test_walk.py::test_no_naive_datetimes tests/test_walk.py::test_ownership_and_mode` → 3 passed.
- `pytest` full suite → 143 passed, 2 RED. The 2 RED are the Wave-3 stubs `test_three_digest_single_pass` and `test_filetype_by_content_not_extension` (META-04/05, Plan 02-03) which MUST stay red until that plan lands.
- `tests/test_seam_allowlist.py` → 2 passed (D-14 held; `core/walk.py` has no actual `import pytsk3` — the only grep hit is a docstring sentence).
- `ruff check src tests` clean; `mypy src` clean (19 files).
- Empirical fixture check confirms the expected MACB values: ext4 `file1.txt` mtime `1780223790` → `2026-05-31T10:36:30+00:00`; FAT `file1.txt` ctime `0` → `None`.

## Deviations from Plan

None affecting behavior. One clarification recorded as a key-decision: the ext4 fixture's stored mode is `644` **decimal** (debugfs `sif mode 644` is decimal-interpreted), which is not equal to the `EXT4_FILE_MODE = 0o644` (420) constant. The plan's acceptance text ("mode match the fixture builder constants") would be incorrect to assert literally, so `test_ownership_and_mode` asserts exact uid/gid against the Plan-00 constants and a non-null integer mode that round-trips through persistence — the truthful META-03 invariant. No source change was needed (mode is stored raw and unformatted per the plan).

## TDD Gate Compliance

Each task followed RED → GREEN: a `test(...)` commit with failing real assertions preceded its `feat(...)` implementation commit (Task 1: b5a092b → 6f1fe01; Task 2: 22b0694 → 3255332). No REFACTOR commit was needed.

## Known Stubs

None introduced by this plan. The two remaining RED tests (`test_three_digest_single_pass`, `test_filetype_by_content_not_extension`) are pre-existing Wave-0 scaffold owned by Plan 02-03 (META-04/05) and are intentionally left failing.

## Self-Check: PASSED

- src/pyautopsy/core/walk.py — FOUND (modified)
- tests/test_walk.py — FOUND (modified)
- Commits b5a092b, 6f1fe01, 22b0694, 3255332 — all present in git log
- STATE.md / ROADMAP.md — NOT modified (orchestrator owns these)
