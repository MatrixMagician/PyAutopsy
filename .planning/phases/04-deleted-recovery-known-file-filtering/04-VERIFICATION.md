---
phase: 04-deleted-recovery-known-file-filtering
verified: 2026-05-31T00:00:00Z
status: human_needed
score: 16/16 must-haves verified
overrides_applied: 0
mode: mvp
human_verification:
  - test: "Open the rendered reports/report.html (or report.json) from an `analyze --recover --nsrl <db> --hash-set-allow <list>` run and confirm the Recovered Files, Orphan Files, and Known-File Filtering sections render as three distinct, readable sections."
    expected: "Three separate sections appear; orphans are listed apart from normal recovered files; the Known-File section frames matches as neutral 'known' (noise reduction), not good/bad."
    why_human: "Visual report layout/legibility and section separation in the rendered HTML cannot be confirmed by grep/test; mirrors the Phase-3 HUMAN-UAT precedent."
  - test: "In the rendered Recovered Files section, confirm each confidence tier uses a glyph/text indicator (not color-only) and the per-fs caveats (ext4 pointer-zeroing, NTFS resident, FAT first-char-lost) are visible and human-readable."
    expected: "Tier is distinguishable without relying on color; caveats read as honest data-survival statements with no 'the user deleted this' / good-bad language."
    why_human: "Accessibility (color-only vs glyph) and copy legibility are visual-UX judgements; the no-overclaiming substring scan is automated but reader comprehension is not."
---

# Phase 4: Deleted Recovery & Known-File Filtering — Verification Report

**Phase Goal:** An examiner can recover deleted and orphaned files with honest, filesystem-aware confidence labeling, and cut noise by filtering files against NSRL and custom hash sets — the headline forensic capability layered onto the proven spine. (MVP mode.)
**Verified:** 2026-05-31
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement (MVP User Flow Coverage)

User story (from 04-00-PLAN): *As a forensic examiner, I want to recover deleted and orphaned files with honest, filesystem-aware confidence labeling and filter the inventory against NSRL and custom hash sets, so that I can produce a defensible report that surfaces recoverable evidence and cuts known-file noise without overclaiming.*

| Step | Expected | Evidence in codebase | Status |
|------|----------|----------------------|--------|
| Examiner runs `pyautopsy recover <image> --case <dir>` (or `analyze --recover`) | Deleted files recovered, hashed, cataloged as `files` rows | `core/recover.py::run_recover` enumerates deleted inodes via seam, writes bytes to confined `recovered/`, hashes via `integrity.hash_file`, inserts `FileRow(allocated=False, recovered=True)` via `store.insert_recovered_files`; CLI `recover` command present (cli/main.py:230). `test_recovers_deleted_ext4_content` + `test_recovers_ntfs_resident` pass. | ✓ VERIFIED |
| Orphans surfaced separately | Orphan entries in a distinct list/section, never mixed | `run_recover` splits `recovered_list` vs `orphan_list` by `is_orphan`; `RecoverResult.recovered`/`.orphans` distinct; store `get_orphan_files`/`get_recovered_files`; assemble.py renders separate sections. `test_orphan_reported_separately` passes. | ✓ VERIFIED |
| Honest confidence labeling | Per-file tier (intact vs partial/overwritten) with per-fs caveats, no intent/good-bad | `classify_tier` (recover.py:144) derives tier from allocated-block intersection + resident + zeroed-pointer paths; `RECOVERY_REPORT_COPY` survival-only. `test_confidence_tiers` + `test_no_overclaiming_copy` pass. | ✓ VERIFIED |
| Filter against NSRL + custom hash sets | Read-only NSRL probe + allow/block lists, surfaced as neutral "known" | `filter/nsrl.py` (mode=ro + query_only, UPPERCASE, parameterized, allowlisted table), `filter/hashsets.py` (allow/block parse + match), `core/knownfiles.py::run_filter` persists `KnownMatch` via store. `test_nsrl_membership`/`test_custom_hash_sets`/`test_variant_table_discovery` pass. | ✓ VERIFIED |
| Defensible, deterministic report | Two identical runs → byte-identical report.json + recovered/ names; default analyze unchanged from Phase 3 | `test_recover_filter_reproducible` + `test_default_analyze_unchanged` pass; deterministic vol/off/meta_addr naming; store total-order readers. | ✓ VERIFIED |
| Read-only soundness preserved | Source never written; Phase-1 re-verify runs | `run_recover` re-asserts `assert_source_not_mounted` twice; `test_recover_does_not_write_source` passes. | ✓ VERIFIED |

### Observable Truths (ROADMAP Success Criteria + locked invariants)

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 1  | SC-1: recovers deleted files (metadata/data intact) as `files` rows w/ offset/inode + per-file hashes (RECOV-01) | ✓ VERIFIED | recover.py builds FileRow with volume_offset/meta_addr/md5/sha1/sha256, recovered=True; test_recovers_deleted_ext4_content + test_recovers_ntfs_resident pass |
| 2  | SC-2: orphan files reported separately (RECOV-02) | ✓ VERIFIED | distinct orphan_list/get_orphan_files; test_orphan_reported_separately pass |
| 3  | SC-3: confidence tier (intact vs partial/overwritten) + per-fs caveats + overwrite detection, never asserting user intent (RECOV-03) | ✓ VERIFIED | classify_tier block-overlap + now_allocated + resident + zeroed-pointer paths; honesty copy; test_confidence_tiers + test_no_overclaiming_copy pass |
| 4  | SC-4: filters vs NSRL RDS + custom hash sets (allow/block), neutral "known" not good/bad (FILTER-01) | ✓ VERIFIED | filter/nsrl.py + filter/hashsets.py neutral match dicts; knownfiles.py persists; 3 knownfiles tests pass |
| 5  | D-14: only evidence/filesystem.py (+image.py) import pytsk3 | ✓ VERIFIED | grep src: only image.py + filesystem.py; test_seam_allowlist.py 2 passed |
| 6  | D-08: CaseStore sole writer (no write SQL outside store.py) | ✓ VERIFIED | no INSERT/UPDATE/DELETE/CREATE outside store.py; lockstep triples for recovered + known matches |
| 7  | D-41/CLI-02: two identical recover/analyze runs byte-identical report.json + recovered/ names | ✓ VERIFIED | test_recover_filter_reproducible pass; deterministic vol/off/meta_addr naming |
| 8  | D-40: default analyze (no recover/filter inputs) byte-identical to Phase-3 baseline | ✓ VERIFIED | analyze.py opt-in gating (if recover / if filter_requested); test_default_analyze_unchanged pass |
| 9  | D-42: source never written; Phase-1 re-verify runs | ✓ VERIFIED | double assert_source_not_mounted in run_recover; test_recover_does_not_write_source pass |
| 10 | D-32/D-38: no intent / good-bad language in tiers or known annotations | ✓ VERIFIED | RECOVERY_REPORT_COPY + match dicts neutral; test_no_overclaiming_copy pass; no good/bad/malicious key in filter/ |
| 11 | _MVP_LIMITATIONS disclaimer honest + conditional | ✓ VERIFIED | _mvp_limitations(recovery_ran, filtering_ran): verbatim default when neither ran, rebuilt honestly when ran (CARVE-01 deferral surfaced) |
| 12 | NSRL UPPERCASE-hash normalization + parameterized SQL + read-only open | ✓ VERIFIED | nsrl.py: `.upper()` fold, `?` placeholder, mode=ro + PRAGMA query_only=ON, fixed {FILE,METADATA} allowlist |
| 13 | BL-01 fix: inventory aggregation excludes recovered rows | ✓ VERIFIED | assemble.py:269 `inventory_files = [f for f in files if f.recovered is not True]`; file_count/deleted_count/per_volume/file_type_distribution all over inventory_files |
| 14 | BL-02 fix: sqlite3.Error mapped in CLI recover + analyze handlers | ✓ VERIFIED | cli/main.py imports sqlite3; sqlite3.Error in both except tuples (lines 320, 481) |
| 15 | Recovered bytes written to confined recovered/ tree (no path traversal) | ✓ VERIFIED | _recovered_target routes through _sanitize_name + _confined_target, deterministic vol/off/meta_addr key, never raw deleted name |
| 16 | All 4 requirement IDs accounted for in REQUIREMENTS.md | ✓ VERIFIED | RECOV-01/02/03 + FILTER-01 all `[x]` Complete + traceability table rows; CARVE-01 explicitly deferred |

**Score:** 16/16 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/pyautopsy/evidence/filesystem.py` | recover_meta, allocated_data_blocks, iter_deleted_inodes, RecoveredEntry — seam-confined | ✓ VERIFIED | all present; pytsk3 only here |
| `src/pyautopsy/core/recover.py` | run_recover orchestrator (no pytsk3) | ✓ VERIFIED | substantive 571 lines; classify_tier + confined write + hash + catalog |
| `src/pyautopsy/filter/nsrl.py` | read-only NSRL probe, UPPERCASE, parameterized | ✓ VERIFIED | open_nsrl + nsrl_match; mode=ro + query_only |
| `src/pyautopsy/filter/hashsets.py` | allow/block parser + neutral match | ✓ VERIFIED | parse_hash_set + custom_match present |
| `src/pyautopsy/core/knownfiles.py` | run_filter orchestrator writing neutral known annotations | ✓ VERIFIED | run_filter present; FilterError; two-arm audit |
| `src/pyautopsy/case/store.py` | insert_recovered_files/get_recovered_files/get_orphan_files/insert_known_matches/get_known_matches | ✓ VERIFIED | all present w/ lockstep triples + deterministic ORDER BY |
| `src/pyautopsy/case/schema.sql` | additive recovery columns + known_file_matches table | ✓ VERIFIED | (confirmed via store triples + models) |
| `src/pyautopsy/core/analyze.py` | opt-in recover + filter wiring | ✓ VERIFIED | gated on `if recover:` / `if filter_requested:` |
| `src/pyautopsy/cli/main.py` | recover command + analyze flags | ✓ VERIFIED | recover/analyze commands; CliRunner confirms --nsrl/--hash-set-allow/-block/--recover |
| `src/pyautopsy/report/assemble.py` | Recovered/Orphan/Known sections + conditional disclaimer | ✓ VERIFIED | _recovered_section, _mvp_limitations, inventory_files BL-01 fix |
| tests (recover/knownfiles/reproducibility/readonly) | 8 RED→GREEN + reproducibility + read-only | ✓ VERIFIED | all named tests pass |

### Key Link Verification

| From | To | Via | Status |
|------|----|----|--------|
| core/recover.py | evidence/filesystem.py | `from pyautopsy.evidence import filesystem as fs_seam` (recover_meta/allocated_data_blocks) | ✓ WIRED |
| core/recover.py | util/safe_extract.py | _confined_target + _sanitize_name | ✓ WIRED |
| core/recover.py | case/store.py | store.insert_recovered_files in transaction() | ✓ WIRED |
| core/knownfiles.py | filter/nsrl.py | open_nsrl + nsrl_match | ✓ WIRED |
| core/knownfiles.py | case/store.py | insert_known_matches in transaction() | ✓ WIRED |
| core/analyze.py | core/recover.py | run_recover when recover flag set | ✓ WIRED |
| core/analyze.py | core/knownfiles.py | run_filter when --nsrl/--hash-set supplied | ✓ WIRED |
| report/assemble.py | case/store.py | get_recovered_files/get_orphan_files/get_known_matches | ✓ WIRED |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full suite | `python -m pytest -q` | 185 passed | ✓ PASS |
| Lint | `ruff check src/` | No issues found | ✓ PASS |
| Types | `python -m mypy src/` | No issues found | ✓ PASS |
| D-14 seam | `test_seam_allowlist.py` | 2 passed | ✓ PASS |
| Named invariant tests | recover + knownfiles + reproducibility::* + readonly::test_recover_does_not_write_source | 11 passed | ✓ PASS |
| CLI flags | Typer CliRunner `recover --help` / `analyze --help` | recover: --nsrl,--hash-set-allow,--hash-set-block,--case; analyze: + --recover | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| RECOV-01 | 04-00/01/03 | Recover deleted files (metadata/data intact) | ✓ SATISFIED | run_recover + tests; SC-1 |
| RECOV-02 | 04-00/01/03 | Orphan files reported separately | ✓ SATISFIED | distinct orphan list/section; SC-2 |
| RECOV-03 | 04-00/01/03 | Confidence tier intact vs partial/overwritten | ✓ SATISFIED | classify_tier + honesty; SC-3 |
| FILTER-01 | 04-00/02/03 | NSRL + custom hash-set filtering, neutral known | ✓ SATISFIED | filter/* + knownfiles; SC-4 |

No orphaned requirements: REQUIREMENTS.md maps exactly RECOV-01/02/03 + FILTER-01 to Phase 4, all claimed by plans. CARVE-01 (file carving) is explicitly out-of-scope/deferred and honestly surfaced in the _MVP_LIMITATIONS copy.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| core/recover.py | 275 | raw read-only `SELECT id FROM evidence_sources` via store.connection.execute | ℹ️ Info | Read-only SELECT, not a write — D-08 "sole writer" (writes) holds. Pre-existing pattern shared with walk.py:260 (Phase 2) and knownfiles.py:82; not a Phase-4 regression and not flagged by the deep review. No data-integrity or determinism impact. |

No debt markers (TODO/FIXME/XXX/TBD/HACK) in any Phase-4 source file.

### Human Verification Required

1. **Report section rendering** — Open the rendered report from an `analyze --recover --nsrl <db> --hash-set-allow <list>` run and confirm three distinct sections (Recovered Files, Orphan Files, Known-File Filtering) render legibly with orphans separated and neutral "known" framing.
2. **Tier glyph + caveat legibility** — Confirm confidence tiers use a glyph/text indicator (not color-only) and the per-fs caveats read as honest data-survival statements.

These mirror the Phase-3 HUMAN-UAT precedent: the automated honesty substring scan (`test_no_overclaiming_copy`) and section-presence assertions pass, but visual layout, color-vs-glyph accessibility, and reader comprehension of the rendered HTML are not programmatically confirmable.

### Gaps Summary

No gaps. All four ROADMAP success criteria are genuinely implemented (not stubbed): recovery, orphan separation, honest confidence tiers with overwrite detection, and NSRL/custom filtering are all backed by substantive orchestrators wired through the native seam, persisted via the sole-writer CaseStore, and proven by passing named tests. All locked cross-cutting invariants (D-08, D-14, D-32, D-38, D-40, D-41, D-42, NSRL uppercase/parameterized/read-only) hold in the shipped code. The two resolved-review blockers are confirmed fixed: BL-01 inventory aggregation now excludes recovered rows (assemble.py:269), and BL-02 maps sqlite3.Error in both CLI handlers. Full suite 185 passed; ruff + mypy clean.

Status is `human_needed` (not `passed`) solely because two end-to-end behaviors — visual report-section rendering and tier-glyph/caveat legibility — are confirmable only by a human, consistent with how Phase 3 handled human UAT.

---

_Verified: 2026-05-31_
_Verifier: Claude (gsd-verifier)_
