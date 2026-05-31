---
phase: 04-deleted-recovery-known-file-filtering
verified: 2026-05-31T19:30:00Z
status: passed
score: 16/16 must-haves verified
overrides_applied: 0
mode: mvp
re_verification:
  previous_status: human_needed
  previous_score: 16/16
  gaps_closed:
    - "RECOV-02: root-level deleted files were mislabelled is_orphan=True (empty Recovered Files; root deletions dumped under Orphan Files with a false 'parent directory is itself gone' provenance claim). Fixed by 04-04 (walk_fs tags root entries with int(fs.info.root_inum); None reserved for the pass-2 range-scan orphan) + WR-01 hardening (root seeded into allocated_inodes scan)."
  gaps_remaining: []
  regressions: []
---

# Phase 4: Deleted Recovery & Known-File Filtering — Verification Report (Re-verification)

**Phase Goal:** An examiner can recover deleted and orphaned files with honest, filesystem-aware confidence labeling, and cut noise by filtering files against NSRL and custom hash sets — the headline forensic capability layered onto the proven spine. (MVP mode.)
**Verified:** 2026-05-31
**Status:** passed
**Re-verification:** Yes — after RECOV-02 gap closure (plan 04-04, commits a84844f/a15c464/fac4447/a96cfd5). Prior cycle was `human_needed`; the human UAT then found ONE major gap (RECOV-02 root-level misclassification) now fixed and regression-pinned.

## Re-verification Focus

The prior verification scored 16/16 and routed to `human_needed` for two visual-UX checks (report section rendering, tier-glyph/caveat legibility). Human UAT (04-HUMAN-UAT.md) executed both:
- **Test 2 (tiers/caveats/print honesty):** PASS — confirmed text+glyph tiers (`● intact`), honest data-survival caveat copy, no intent language, clean A4 PDF.
- **Test 1 (three sections + classification):** ISSUE (major) — sections rendered and known-file framing was neutral, BUT root-level deletions were mislabelled `is_orphan=True`, emptying Recovered Files and overclaiming orphan provenance (against D-32/RECOV-03).

Plan 04-04 closed Test 1's gap. This re-verification:
1. Full-3-level verification of the RECOV-02 fix (the failed item).
2. Regression check that the genuine-orphan path (RECOV-01/RECOV-03) did NOT break.
3. Regression check that RECOV-01/RECOV-03/FILTER-01 and all locked invariants remain satisfied.

## Goal Achievement (MVP User Flow Coverage)

| Step | Expected | Evidence in codebase | Status |
|------|----------|----------------------|--------|
| Examiner runs `recover`/`analyze --recover` | Deleted files recovered, hashed, cataloged as `files` rows | `core/recover.py::run_recover` enumerates deleted inodes via seam, writes confined bytes, hashes, inserts `FileRow(recovered=True)`. `test_recovers_deleted_ext4_content` + `test_recovers_ntfs_resident` pass. | ✓ VERIFIED |
| Orphans surfaced separately, NOT mixed into Recovered | Root-level deletions (parent survives) → Recovered; only genuine no-parent entries → Orphan | `recover.py:519-522` routes on `is_orphan = di.is_orphan or entry.is_orphan`; seam `iter_deleted_inodes` now classifies a root deletion non-orphan (root inode allocated, tagged as parent_addr). `test_root_deletion_reported_as_recovered_not_orphan`, `test_orphan_reported_separately` pass. **Gap from UAT Test 1 closed.** | ✓ VERIFIED |
| Honest confidence labeling | Per-file tier + per-fs caveats, no intent/good-bad | `classify_tier` (recover.py:144); `RECOVERY_REPORT_COPY` survival-only. `test_confidence_tiers` + `test_no_overclaiming_copy` pass; UAT Test 2 PASS. | ✓ VERIFIED |
| Filter vs NSRL + custom hash sets | Read-only NSRL probe + allow/block, neutral "known" | `filter/nsrl.py` (mode=ro + query_only, UPPERCASE, parameterized, table allowlist), `filter/hashsets.py`, `core/knownfiles.py::run_filter`. 3 knownfiles tests pass. | ✓ VERIFIED |
| Defensible, deterministic report | Identical runs → byte-identical output; default analyze unchanged | `test_recover_filter_reproducible` + `test_default_analyze_unchanged` pass; `parent_addr` now a stable `int` (determinism preserved). | ✓ VERIFIED |
| Read-only soundness preserved | Source never written | double `assert_source_not_mounted`; the 04-04 fix mutates only an in-memory `parent_addr`. `test_recover_does_not_write_source` passes. | ✓ VERIFIED |

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 1  | SC-1 / RECOV-01: recovers deleted files as `files` rows w/ offset/inode + per-file hashes | ✓ VERIFIED | recover.py builds FileRow with volume_offset/meta_addr/md5/sha1/sha256, recovered=True; test_recovers_deleted_ext4_content + test_recovers_ntfs_resident pass |
| 2  | **SC-2 / RECOV-02: orphan files reported separately — root-level deletions are NOT mislabelled orphan** | ✓ VERIFIED (gap closed) | walk_fs:728-730 tags root entries with `int(fs.info.root_inum)`; iter_deleted_inodes:479-481 orphan check; recover.py:519-522 split. `test_root_level_deletion_is_not_orphan`, `test_root_deletion_reported_as_recovered_not_orphan`, `test_removed_parent_deletion_is_still_orphan` all pass. Independent revert simulation: 4 tests FAIL on revert (gate is real). |
| 3  | SC-3 / RECOV-03: confidence tier + per-fs caveats, never asserting user intent | ✓ VERIFIED | classify_tier + honesty copy; test_confidence_tiers + test_no_overclaiming_copy pass; UAT Test 2 PASS. The false "parent directory is itself gone" overclaim for root deletions (a RECOV-03/D-32 violation) is gone. |
| 4  | SC-4 / FILTER-01: NSRL RDS + custom hash sets, neutral "known" | ✓ VERIFIED | filter/nsrl.py + filter/hashsets.py + knownfiles.py; 3 tests pass; UAT Test 1 confirmed neutral framing |
| 5  | D-14: only evidence/filesystem.py (+image.py) import pytsk3 | ✓ VERIFIED | test_seam_allowlist.py passes; the 04-04 fix added no new pytsk3 importer |
| 6  | D-08: CaseStore sole writer | ✓ VERIFIED | no write SQL outside store.py; recover writes via store.insert_recovered_files in transaction() |
| 7  | D-41/CLI-02: identical runs byte-identical | ✓ VERIFIED | test_reproducibility passes; parent_addr now deterministic int |
| 8  | D-40: default analyze byte-identical to Phase-3 baseline | ✓ VERIFIED | test_default_analyze_unchanged pass |
| 9  | D-42: source never written | ✓ VERIFIED | double assert_source_not_mounted; 04-04 fix is in-memory only; test_recover_does_not_write_source pass |
| 10 | D-32/D-38: no intent / good-bad language; no false orphan provenance | ✓ VERIFIED | neutral copy; root deletions no longer carry false "parent gone" claim |
| 11 | _MVP_LIMITATIONS disclaimer honest + conditional | ✓ VERIFIED | _mvp_limitations(recovery_ran, filtering_ran) |
| 12 | NSRL UPPERCASE + parameterized SQL + read-only open | ✓ VERIFIED | nsrl.py .upper() + ? placeholder + mode=ro + PRAGMA query_only |
| 13 | BL-01 fix: inventory aggregation excludes recovered rows | ✓ VERIFIED | assemble.py inventory_files filter |
| 14 | BL-02 fix: sqlite3.Error mapped in CLI recover + analyze | ✓ VERIFIED | sqlite3.Error in both except tuples |
| 15 | Recovered bytes written to confined recovered/ tree (no traversal) | ✓ VERIFIED | _recovered_target via _sanitize_name + _confined_target |
| 16 | All 4 requirement IDs accounted for in REQUIREMENTS.md | ✓ VERIFIED | RECOV-01/02/03 + FILTER-01 all `[x]` Complete + traceability rows; CARVE-01 explicitly deferred to v2 |

**Score:** 16/16 truths verified

### RECOV-02 Fix — Three-Level Verification (the previously failed item)

| Level | Check | Result |
|-------|-------|--------|
| 1 Exists | `root_inum` substitution in walk_fs | ✓ filesystem.py:728-730 (`if _depth == 0 and parent_addr is None: resolved_parent_addr = int(fs.info.root_inum)`) |
| 1 Exists | WR-01 hardening (root seeded into scan) | ✓ filesystem.py:424,429 (`root = int(fs.info.root_inum)`; `for inum in {root, *range(first, last + 1)}`) — confirmed in COMMITTED tree (git show HEAD) |
| 2 Substantive | Guard fires only at genuine root call | ✓ recursive call passes child `meta_addr` (non-None), so None stays reserved for pass-2 orphan (filesystem.py:529, parent_addr=None unchanged) |
| 3 Wired | Seam → orchestrator split | ✓ recover.py:443 `is_orphan = di.is_orphan or entry.is_orphan`; :519-522 routes orphan_list vs recovered_list |
| 4 Data-flow / behavior | Both directions pinned, fails on revert | ✓ revert simulation broke 4 tests (test_root_level_deletion_is_not_orphan, test_root_entries_carry_root_inode_parent_addr, test_parent_addr_threaded_through_recursion, test_root_deletion_reported_as_recovered_not_orphan); restored cleanly |

### Key Link Verification

| From | To | Via | Status |
|------|----|----|--------|
| walk_fs (root call) | iter_deleted_inodes | parent_addr = root_inum (allocated) → parent_known_orphan False for root deletions | ✓ WIRED |
| iter_deleted_inodes | core/recover.py split | DeletedInode.is_orphan drives orphan_list vs recovered_list | ✓ WIRED |
| core/recover.py | case/store.py | insert_recovered_files in transaction() | ✓ WIRED |
| core/knownfiles.py | filter/nsrl.py + hashsets.py | open_nsrl + nsrl_match + custom_match | ✓ WIRED |
| report/assemble.py | case/store.py | get_recovered_files/get_orphan_files/get_known_matches | ✓ WIRED |

### Behavioral Spot-Checks / Probe Execution

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| RECOV-02 regression + seam + reproducibility | `pytest test_filesystem test_recover test_seam_allowlist test_reproducibility` | 26 passed | ✓ PASS |
| Full suite | `pytest -q` | 188 passed | ✓ PASS |
| Revert-detection (independent) | restore buggy `parent_addr=None` at root | 4 RECOV-02 tests FAIL (gate catches revert) | ✓ PASS |
| Committed FAT root-deletion fixture | `git ls-files tests/fixtures/tiny_fat32.img` | tracked; FAT_DELETED_META_ADDR=4 | ✓ PASS |
| Debt markers in changed source | grep TODO/FIXME/XXX/TBD/HACK in filesystem.py + recover.py | none | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| RECOV-01 | 04-00/01/03 | Recover deleted files (metadata/data intact) | ✓ SATISFIED | run_recover + tests; not regressed by 04-04 |
| RECOV-02 | 04-00/01/03/**04** | Orphan files reported separately | ✓ SATISFIED | gap closed — root deletions Recovered, genuine orphans Orphan; both directions pinned |
| RECOV-03 | 04-00/01/03 | Confidence tier intact vs partial/overwritten, no overclaim | ✓ SATISFIED | classify_tier + honesty; false root-orphan overclaim removed |
| FILTER-01 | 04-00/02/03 | NSRL + custom hash-set filtering, neutral known | ✓ SATISFIED | filter/* + knownfiles |

All four Phase-4 requirement IDs (RECOV-01/02/03, FILTER-01) are claimed by plans and verified. No orphaned requirements: REQUIREMENTS.md maps exactly these four to Phase 4. CARVE-01 / RECOV-04 are explicitly v2/out-of-scope.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| core/recover.py | ~275 | read-only `SELECT id FROM evidence_sources` via store.connection | ℹ️ Info | Read-only SELECT (not a write); D-08 sole-WRITER invariant holds. Pre-existing, not a 04-04 regression. |

No debt markers (TODO/FIXME/XXX/TBD/HACK) in any Phase-4 source file. No new dependency added by 04-04.

### Advisory Warnings (from 04-04-REVIEW.md — non-blocking, NOT gaps)

- **WR-01** (root-inode tagging breaks if `first_inum > root_inum`): ADDRESSED in committed code — `allocated_inodes` now seeds `{root, *range(first, last+1)}` (filesystem.py:424,429, commit fac4447), decoupling the orphan check from the scan floor.
- **WR-02** (hard-coded fixture inode addresses are unverified ground-truth): test-quality robustness only; does not affect production behavior or the RECOV-02 guarantee. Tracked as advisory.
- **IN-02** (stale non-editable site-packages install can mask the fix in an ad-hoc REPL): environment hygiene, not a code defect. The test harness is insulated via `pyproject.toml pythonpath=["src"]`; verified by running tests under that config (188 passed).

### Gaps Summary

No gaps. The single RECOV-02 gap raised by human UAT (Test 1) is genuinely closed in the codebase: `walk_fs` tags root-level entries with the allocated root inode and reserves `None` exclusively for the pass-2 no-dir-link orphan; `allocated_inodes` seeds the root inode so classification never depends on the `first_inum` floor (WR-01). The fix is wired through `iter_deleted_inodes` → `core/recover.py`'s orphan/recovered split, and is regression-pinned in BOTH directions for BOTH FAT and ext4 — independently confirmed to fail on a simulated revert. The genuine-orphan path (RECOV-01/RECOV-03) is preserved (`test_orphan_reported_separately`, `test_removed_parent_deletion_is_still_orphan` pass). RECOV-01, RECOV-03, FILTER-01 and all locked invariants (D-08/D-14/D-32/D-38/D-40/D-41/D-42, NSRL uppercase/parameterized/read-only) remain satisfied. Full suite 188 passed.

**Status is `passed`:** the human-testing dimension was already exercised by the prior UAT cycle (Test 2 PASS; Test 1's sole gap now fixed and regression-pinned), the deep review returned 0 blockers, and codebase evidence confirms the fix. No remaining items require human testing.

---

_Verified: 2026-05-31_
_Verifier: Claude (gsd-verifier)_
_Mode: re-verification after gap closure (RECOV-02)_
