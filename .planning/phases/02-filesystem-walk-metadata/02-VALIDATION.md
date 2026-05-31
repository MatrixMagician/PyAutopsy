---
phase: 2
slug: filesystem-walk-metadata
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-31
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from 02-RESEARCH.md §"Validation Architecture".

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (already configured) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (`pythonpath=["src"]`, `testpaths=["tests"]`) |
| **Quick run command** | `python3 -m pytest tests/test_filesystem.py tests/test_walk.py -x` |
| **Full suite command** | `python3 -m pytest` |
| **Estimated runtime** | ~15 seconds (tiny committed fixture images) |

---

## Sampling Rate

- **After every task commit:** Run `python3 -m pytest tests/test_filesystem.py tests/test_walk.py -x`
- **After every plan wave:** Run `python3 -m pytest`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** ~15 seconds
- **"Every file" coverage signal:** each fixture asserts an **exact expected row count** (created entries + known deleted entry + expected system files), not spot-checks — the Nyquist signal that the walk inventoried *every* file.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 2-W0 | 00 | 0 | infra | — | Source never mounted/written | fixtures+arch | `pytest tests/test_seam_allowlist.py -x` | ❌ W0 | ⬜ pending |
| 2-META-01a | — | — | META-01 | — | Inventory incl. deleted entry; alloc/unalloc + inode addr | unit/integration | `pytest tests/test_walk.py::test_inventory_includes_deleted_entry -x` | ❌ W0 | ⬜ pending |
| 2-META-01b | — | — | META-01 | — | Bare-FS (offset 0) + partitioned image walked; rows tagged volume_id/offset | integration | `pytest tests/test_filesystem.py::test_volume_enumeration -x` | ❌ W0 | ⬜ pending |
| 2-META-02a | — | — | META-02 | — | MACB tz-aware UTC ISO-8601 `+00:00`; FAT flagged `local-time-inferred`; zero→None | unit | `pytest tests/test_walk.py::test_macb_utc_and_fat_flagged -x` | ❌ W0 | ⬜ pending |
| 2-META-02b | — | — | META-02 | — | **No naive datetimes**: every `*time` column parses to an aware datetime | unit (invariant) | `pytest tests/test_walk.py::test_no_naive_datetimes -x` | ❌ W0 | ⬜ pending |
| 2-META-03 | — | — | META-03 | — | uid/gid/mode persisted, match fixture | unit | `pytest tests/test_walk.py::test_ownership_and_mode -x` | ❌ W0 | ⬜ pending |
| 2-META-04 | — | — | META-04 | — | MD5+SHA1+SHA256 single pass match hashlib; empty→sentinel; `--max-hash-size` skips+records | unit | `pytest tests/test_walk.py::test_three_digest_single_pass -x` | ❌ W0 | ⬜ pending |
| 2-META-05 | — | — | META-05 | — | `file_type` by content (text typed `text/plain` despite misleading extension) | unit | `pytest tests/test_walk.py::test_filetype_by_content_not_extension -x` | ❌ W0 | ⬜ pending |
| 2-D20 | — | — | success-crit 5 | T-2-01 | Unsupported/garbage-offset volume → limitation finding, walk continues, no garbage rows | integration | `pytest tests/test_walk.py::test_unsupported_volume_records_limitation -x` | ❌ W0 | ⬜ pending |
| 2-D14 | — | — | D-14 arch | — | No `pytsk3` import outside `evidence/image.py` + `evidence/filesystem.py` | unit (arch guard) | `pytest tests/test_seam_allowlist.py -x` | ❌ W0 | ⬜ pending |
| 2-RO | — | — | D-05/P1 | T-2-02 | Walk never mounts/writes source (mtime+size unchanged after walk) | integration | `pytest tests/test_readonly_guarantee.py::test_source_unchanged_after_walk -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky. Plan/Wave/Task-ID columns finalized by the planner.*

---

## Wave 0 Requirements

- [ ] `tests/fixtures/make_fixtures.py` — `build_tiny_ext4_image` (`mkfs.ext4 -F` + debugfs write/rm for a deleted entry), `build_tiny_fat32_image` (`mkfs.fat -F 32`, ≥64MB, `MTOOLS_SKIP_CHECK=1 mcopy`), `build_tiny_ntfs_image` (`mkntfs -F -Q`), `build_partitioned_image` (parted/sfdisk + 2 FS for volume-offset test). Commit the tiny built images to keep CI mkfs-free (mirrors existing `tiny_raw.dd`).
- [ ] `tests/test_filesystem.py` — seam-level: volume enumeration, bare-FS fallback, FS-type detection, `OSError`→limitation, recursion correctness.
- [ ] `tests/test_walk.py` — orchestrator tests covering META-01..05 + D-20.
- [ ] `tests/test_seam_allowlist.py` — arch guard making the D-14 grep gate **executable** (currently only a convention).
- [ ] `tests/test_readonly_guarantee.py` — extend with `test_source_unchanged_after_walk`.
- [ ] Deps: add `python-magic==0.4.27`; ensure `file-magic` is **absent / not shadowing** in the test env (both are installed on this host — import-collision hazard).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real partitioned multi-FS disk image at scale | META-01 (volume offsets) | Session only built bare-FS + a small synthetic partitioned fixture; large real-world partition tables not exercised in CI | On a partitioned E01/dd, run the walk and confirm each volume's rows carry the correct `volume_id`/byte-offset |
| Sub-second / nano MACB folding | META-02 (D-16) | The committed ext4 fixture has `mtime_nano=0` (debugfs does not set it — Assumption A3), so the `*_nano`→`attributes` fold branch has no green automated target; real images differ | On a real ext4/NTFS image with non-zero `*_nano`, run the walk and confirm `attributes` carries the sub-second values for at least one file |

*All other phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 20s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
