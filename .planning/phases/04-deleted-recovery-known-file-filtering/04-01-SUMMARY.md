---
phase: 04-deleted-recovery-known-file-filtering
plan: 01
subsystem: recovery
tags: [pytsk3, recovery, deleted-files, orphans, confidence-tier, ntfs-resident, ext4, safe-extract, typer, jinja2, tdd]

# Dependency graph
requires:
  - phase: 02-filesystem-walk
    provides: the evidence/filesystem.py native seam (FileEntry/_make_reader/walk_fs), CaseStore files-table write/read path, FileRow model, integrity.hash_file single-pass hashing, util/safe_extract confinement jail
  - phase: 03-timeline-mvp-report
    provides: assemble_report_body deterministic-dict pattern, the WR-02 honesty-test discipline, report.html.j2 section pattern
  - phase: 04-deleted-recovery-known-file-filtering
    plan: 00
    provides: the five deterministic fixtures (ext4 orphan/overwritten, NTFS resident-deleted, NSRL FILE/METADATA DBs) + the eight named RED stubs + ground-truth constants
provides:
  - Seam recovery helpers (recover_meta/RecoveredEntry, allocated_data_blocks, allocated_inodes, iter_deleted_inodes/DeletedInode, fs_type_int) — all pytsk3 confined to filesystem.py
  - core/recover.py run_recover orchestrator (no pytsk3): tier classification, confined write, single-pass hash, recovered-row catalog, separate orphan list
  - Additive recovery schema columns + CaseStore insert_recovered_files / get_recovered_files / get_orphan_files (sole writer, D-26 order)
  - `pyautopsy recover` CLI command + deterministic Recovered/Orphan report sections (HTML + JSON body)
affects: [filtering-slice, integration-slice, "plan 04-02 (knownfiles)", "plan 04-03 (analyze wiring + _MVP_LIMITATIONS update)"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Seam-confined deleted-inode recovery: open_meta(inode) + read_random closure + TSK_FS_ATTR_RUN run enumeration, returning plain ints + a read closure (no native object escapes the D-14 seam)"
    - "Derived allocated-block set (pytsk3 has no block-bitmap API): walk every allocated inode's non-resident runs once, then intersect with a deleted file's runs for the confidence tier"
    - "Two-pass deleted-inode discovery: directory walk (name/path/parent for surviving dir links) unioned with an inode-range scan (broken name->meta links, e.g. NTFS resident-deleted)"
    - "Orphan-ness from parent survival (parent_addr not in the allocated-inode set) unioned with the TSK ORPHAN meta flag — not the meta flag alone"
    - "Deterministic, confined recovered/ writes keyed by vol/off/meta_addr via safe_extract _confined_target/_sanitize_name (never the raw deleted name)"

key-files:
  created:
    - src/pyautopsy/core/recover.py
  modified:
    - src/pyautopsy/evidence/filesystem.py
    - src/pyautopsy/case/schema.sql
    - src/pyautopsy/case/models.py
    - src/pyautopsy/case/store.py
    - src/pyautopsy/cli/main.py
    - src/pyautopsy/report/assemble.py
    - src/pyautopsy/report/templates/report.html.j2

decisions:
  - "Enumerate deleted inodes through a new seam helper iter_deleted_inodes (directory-walk + inode-range scan) rather than a prior walk inventory — the test contract runs ingest->recover with no walk, and NTFS resident-deleted entries lose their name->meta link"
  - "Orphan detection combines parent-survival (parent_addr not allocated / no surviving dir link) with the TSK ORPHAN meta flag, because the ext4 orphan fixture's surviving (deleted) parent path leaves the ORPHAN meta flag unset"
  - "Recovered rows reuse the files table via four additive DEFAULT NULL columns (recovered, confidence_tier, recovered_path, is_orphan) + attributes JSON for tier rationale/caveats (D-35); CaseStore stays sole writer"
  - "max_hash_size doubles as a recovered-content write cap (size-bomb guard, T-04-01-BOMB)"

requirements: [RECOV-01, RECOV-02, RECOV-03]
requirements-completed: [RECOV-01, RECOV-02, RECOV-03]

# Metrics
duration: ~75min
completed: 2026-05-31
---

# Phase 4 Plan 01: Metadata-Intact Recovery Vertical Slice Summary

**The headline recovery capability end-to-end: deleted ext4 and NTFS-resident files recover their exact bytes through the D-14 native seam, get classified into honest intact/partial-overwritten tiers from a derived allocated-block set, are written to a confined `recovered/` tree and cataloged as `files` rows, with orphans reported separately — all runnable via `pyautopsy recover` and rendered in deterministic Recovered/Orphan report sections.**

## Performance

- **Duration:** ~75 min
- **Completed:** 2026-05-31
- **Tasks:** 3
- **Files modified:** 8 (1 created, 7 modified) — 1208 insertions

## Accomplishments
- **Seam (filesystem.py):** added `recover_meta`/`RecoveredEntry` (open_meta + read_random closure + plain-int block runs + orphan/realloc flags), `allocated_data_blocks` (the derived bitmap — pytsk3 has no `block_walk`, Pitfall 1), `allocated_inodes`, `iter_deleted_inodes`/`DeletedInode` (two-pass discovery), and `fs_type_int`. No native object escapes the seam; `test_seam_allowlist.py` stays green.
- **Orchestrator (core/recover.py):** `run_recover` recovers deleted + orphan + NTFS-resident content with no pytsk3 import — re-asserts read-only (D-42), derives the allocated-block set once per filesystem, re-checks the Pitfall-5 reallocation hazard, classifies tiers via the pure `classify_tier`, writes confined deterministic bytes (D-33/D-34), hashes via `integrity.hash_file` (single pass, D-37), and catalogs `allocated=False` recovered rows via CaseStore in one transaction.
- **Schema/store:** four additive `DEFAULT NULL` recovery columns on `files`; `insert_recovered_files` + `get_recovered_files`/`get_orphan_files` readers in the store's D-26 total order. CaseStore stays sole writer; no raw SQL outside store.py.
- **CLI + report:** `pyautopsy recover <image> --case <dir> [--max-hash-size]`; deterministic "Recovered Files" + separate "Orphan Files" sections in the JSON body and autoescaped HTML, with honest data-survival-only tier copy and a glyph+text tier indicator.
- **Honesty:** `RECOVERY_REPORT_COPY` describes data survival only — `test_no_overclaiming_copy` (the WR-02 mirror) is green; no intent/good-bad substring anywhere in tier or report copy.

## Task Commits

1. **Task 1: Seam recovery helpers + additive recovery schema/store methods** — `7aedfaa` (feat)
2. **Task 2: core/recover.py orchestrator (no pytsk3)** — `30402ab` (feat)
3. **Task 3: pyautopsy recover CLI + Recovered/Orphan report sections** — `12b58cd` (feat)

## Files Created/Modified
- `src/pyautopsy/evidence/filesystem.py` — recovery seam helpers (recover_meta, allocated_data_blocks/inodes, iter_deleted_inodes, fs_type_int) + RecoveredEntry/DeletedInode value objects; new pytsk3 flag constants (UNALLOC/ORPHAN/NONRES/SPARSE).
- `src/pyautopsy/core/recover.py` — NEW run_recover orchestrator + pure classify_tier + RECOVERY_REPORT_COPY + RecoverResult/RecoveredFile (separate recovered/orphan lists).
- `src/pyautopsy/case/schema.sql` — additive recovered/confidence_tier/recovered_path/is_orphan columns on files (DEFAULT NULL, no backfill).
- `src/pyautopsy/case/models.py` — FileRow extended with the four optional recovery fields.
- `src/pyautopsy/case/store.py` — _FILES_COLUMNS/_file_row_params lockstep + get_file read side; insert_recovered_files / get_recovered_files / get_orphan_files.
- `src/pyautopsy/cli/main.py` — `recover` Typer command.
- `src/pyautopsy/report/assemble.py` — deterministic recovered/orphans body sections + _recovered_section projector.
- `src/pyautopsy/report/templates/report.html.j2` — Recovered Files + Orphan Files HTML sections.

## Decisions Made
- **Standalone enumeration via the seam:** the recovery candidate set is built by `iter_deleted_inodes` (a directory walk unioned with an inode-range scan), not from a prior `get_files` walk inventory. This was forced by the test contract (ingest→recover, no walk) AND by NTFS resident-deletion, where the deleted name entry loses its meta reference (`walk_fs` reports `meta_addr is None`) but the inode survives at a known address.
- **Orphan = parent-gone OR ORPHAN flag:** the ext4 orphan fixture's deleted file is still reachable via its (deleted) parent path, so TSK does not set the per-inode ORPHAN flag. Orphan-ness is therefore decided primarily from parent survival (`parent_addr` not in the derived allocated-inode set, or no surviving dir link), unioned with the meta flag.
- **Reuse the files schema (D-35):** recovered rows are `files` rows with `allocated=False`, `recovered=1`, and tier rationale/caveats in `attributes` — no dedicated recovery table.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Recovery enumerates deleted inodes via a new seam helper, not a prior walk inventory**
- **Found during:** Task 2
- **Issue:** The plan's behavior said `run_recover` enumerates `allocated=False` rows from `get_files`. But the Wave-0 test harness (`_ingest_then_recover`) runs `run_ingest` then `run_recover` with **no `run_walk`**, so `get_files` is empty. Additionally, the NTFS resident-deleted entry's directory name loses its meta link (the walk yields `meta_addr is None`), so even a populated inventory would miss inode 64.
- **Fix:** Added `iter_deleted_inodes`/`DeletedInode` + `allocated_inodes` to the seam — a two-pass discovery (directory walk for name/path/parent + inode-range scan for broken-link inodes). `run_recover` now drives this directly, so it is fully standalone and recovers both the named ext4 orphan and the broken-link NTFS resident file.
- **Files modified:** src/pyautopsy/evidence/filesystem.py, src/pyautopsy/core/recover.py
- **Verification:** all five recover tests green; seam-allowlist green (the new helpers live only in filesystem.py).
- **Committed in:** 7aedfaa (seam helpers), 30402ab (orchestrator wiring)

**2. [Rule 1 - Bug] Orphan detection uses parent survival, not the TSK ORPHAN flag alone**
- **Found during:** Task 2
- **Issue:** Empirically, the ext4 orphan fixture's inode 13 does **not** carry the `TSK_FS_META_FLAG_ORPHAN` flag (it is still reachable via its deleted parent path `/secret/orphan.txt`), so a meta-flag-only orphan check classified it as a normal recovered file and `test_orphan_reported_separately` failed.
- **Fix:** `iter_deleted_inodes` computes `is_orphan` from parent survival (`parent_addr` not in the derived allocated-inode set, or no surviving dir link) unioned with the ORPHAN meta flag — matching RESEARCH §Pattern 3's stated fallback.
- **Files modified:** src/pyautopsy/evidence/filesystem.py
- **Verification:** `test_orphan_reported_separately` green; inode 13 appears in the orphan list, not the recovered list.
- **Committed in:** 7aedfaa

**Total deviations:** 2 auto-fixed (1 blocking, 1 bug). No architectural changes; no new packages.

## Authentication Gates
None.

## Issues Encountered
- The `python -m pyautopsy.cli.main recover --help` invocation emitted a harmless runpy "found in sys.modules" warning; verified the command surface (image arg + `--case` + `--max-hash-size`) via `typer.testing.CliRunner` instead.

## Known Stubs
- `tests/test_knownfiles.py` (3 tests: `test_nsrl_membership`, `test_custom_hash_sets`, `test_variant_table_discovery`) remain RED — they reference `pyautopsy.filter`, which is Wave 2 / plan 04-02's job. This is the intended, documented RED floor for the phase, not a defect in this plan.

## Next Phase Readiness
- **Plan 04-02 (filtering)** can implement `filter/nsrl.py` + `filter/hashsets.py` against `test_knownfiles.py` and the NSRL FILE/METADATA DBs.
- **Plan 04-03 (analyze wiring)** will opt-in recovery/filtering into `run_analyze` and update `report/assemble.py::_MVP_LIMITATIONS` (deliberately left unchanged here per the plan note) once both recovery + filtering are wired into `analyze`.

## Self-Check: PASSED

- Created file exists: `src/pyautopsy/core/recover.py` — FOUND.
- Commits present: `7aedfaa`, `30402ab`, `12b58cd` — all FOUND in git history.
- 5 recovery tests + seam-allowlist green; prior 173 + new recovery tests pass (178 total); only the 3 expected-RED knownfiles stubs fail; ruff + mypy clean on all changed files.

---
*Phase: 04-deleted-recovery-known-file-filtering*
*Completed: 2026-05-31*
