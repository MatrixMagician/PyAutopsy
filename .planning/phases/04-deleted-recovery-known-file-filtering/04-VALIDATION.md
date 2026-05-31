---
phase: 4
slug: deleted-recovery-known-file-filtering
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-31
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x (Python 3.x; `pyproject [dependency-groups] dev`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (`pythonpath=["src"]`, `testpaths=["tests"]`) |
| **Quick run command** | `python -m pytest tests/test_recover.py tests/test_knownfiles.py tests/test_seam_allowlist.py -x -q` |
| **Full suite command** | `python -m pytest -q` |
| **Estimated runtime** | ~30 seconds (full suite, incl. fixture image builds) |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_recover.py tests/test_knownfiles.py tests/test_seam_allowlist.py -x -q`
- **After every plan wave:** Run `python -m pytest -q` (full suite, incl. reproducibility + readonly guarantee)
- **Before `/gsd-verify-work`:** Full suite green + `ruff` + `mypy` clean (project gates)
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 4-00-* | 00 | 0 | RECOV-01..03, FILTER-01 | — | Failing test stubs + fixtures committed | unit | `python -m pytest tests/test_recover.py tests/test_knownfiles.py -q` | ❌ W0 | ⬜ pending |
| 4-recov-01 | recovery | 1 | RECOV-01 | T-4-PathTraversal | Recovered name sanitized; write confined to `recovered/` via realpath | unit+integration | `pytest tests/test_recover.py::test_recovers_deleted_ext4_content -x` | ❌ W0 | ⬜ pending |
| 4-recov-02 | recovery | 1 | RECOV-01 | — | NTFS resident `$DATA` from MFT | unit | `pytest tests/test_recover.py::test_recovers_ntfs_resident -x` | ❌ W0 | ⬜ pending |
| 4-recov-03 | recovery | 1 | RECOV-02 | — | Orphan reported in separate list | integration | `pytest tests/test_recover.py::test_orphan_reported_separately -x` | ❌ W0 | ⬜ pending |
| 4-recov-04 | recovery | 1 | RECOV-03 | T-4-InodeReuse | intact vs partial/overwritten via derived block set; ext4 zeroed-pointer caveat | unit | `pytest tests/test_recover.py::test_confidence_tiers -x` | ❌ W0 | ⬜ pending |
| 4-recov-05 | recovery | 1 | RECOV-03 | — | No intent / good-bad copy (mirror Phase-3 WR-02) | unit | `pytest tests/test_recover.py::test_no_overclaiming_copy -x` | ❌ W0 | ⬜ pending |
| 4-filt-01 | filtering | 2 | FILTER-01 | T-4-NSRL-case/SQLi | NSRL membership: UPPERCASE-in-DB vs lowercase row; parameterized SQL; `mode=ro` | unit | `pytest tests/test_knownfiles.py::test_nsrl_membership -x` | ❌ W0 | ⬜ pending |
| 4-filt-02 | filtering | 2 | FILTER-01 | T-4-ListParse | Custom allow/block parse (comments/blank/mixed-case); md5→sha1→sha256; neutral annotation | unit | `pytest tests/test_knownfiles.py::test_custom_hash_sets -x` | ❌ W0 | ⬜ pending |
| 4-filt-03 | filtering | 2 | FILTER-01 | — | `FILE` and `METADATA` variant table discovery | unit | `pytest tests/test_knownfiles.py::test_variant_table_discovery -x` | ❌ W0 | ⬜ pending |
| 4-int-01 | integration | 3 | CLI-02 / D-41 | — | Two runs → byte-identical report.json + identical `recovered/` names | integration | `pytest tests/test_reproducibility.py::test_recover_filter_reproducible -x` | ❌ W0 | ⬜ pending |
| 4-int-02 | integration | 3 | D-40 | — | Default `analyze` (no recover inputs) byte-identical to Phase-3 baseline | integration | `pytest tests/test_reproducibility.py::test_default_analyze_unchanged -x` | ❌ W0 | ⬜ pending |
| 4-int-03 | integration | 3 | D-14 | — | Seam allowlist green (recover/filter import no pytsk3) | unit | `pytest tests/test_seam_allowlist.py -x` | ✅ exists | ⬜ pending |
| 4-int-04 | integration | 3 | D-42 | T-4-ReadOnly | Source bytes unchanged after recover; re-verify runs | integration | `pytest tests/test_readonly_guarantee.py::test_recover_does_not_write_source -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_recover.py` — recovery, orphan, tier, honesty stubs (RECOV-01/02/03)
- [ ] `tests/test_knownfiles.py` — NSRL + custom hash-set matching stubs (FILTER-01)
- [ ] `tests/fixtures/make_fixtures.py` — extend with: ext4 image containing (a) an **orphan** (file + its parent dir deleted), (b) an **overwritten** deleted entry (blocks reclaimed by a new file); an NTFS image with a **resident deleted** file; commit built images with ground-truth constants (mirrors Phase-2 pattern)
- [ ] `tests/fixtures/` — a tiny **NSRL-format SQLite fixture** (`FILE` table, UPPERCASE-hash rows matching fixture-file hashes) + a `METADATA`-variant copy for the discovery test; built deterministically
- [ ] Extend existing `tests/test_reproducibility.py` and `tests/test_readonly_guarantee.py` with recover/filter cases
- [ ] No framework install needed — pytest already present

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Visual review of recovered-files / orphans / known-file sections in rendered report.html | RECOV-01..03, FILTER-01 | Browser render + honest-copy spot-check is best confirmed by eye (automated covers structure + wording assertions) | Run `pyautopsy recover` then `analyze --recover --nsrl <fixture-db>`; open `reports/report.html`; confirm separate Recovered / Orphan / Known sections, tier glyphs (not color-only), and no intent/good-bad language |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
