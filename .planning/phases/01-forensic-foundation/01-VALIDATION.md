---
phase: 1
slug: forensic-foundation
status: approved
nyquist_compliant: true
wave_0_complete: false
created: 2026-05-30
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Greenfield Walking Skeleton — Wave 0 stands up the test infrastructure itself.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (created in Wave 0) |
| **Quick run command** | `pytest -q` |
| **Full suite command** | `pytest -q --maxfail=1` |
| **Estimated runtime** | ~15 seconds |

Native deps for the full suite: `sleuthkit`/`libtsk` (raw ingest). E01 tests
require `libewf` + the `[ewf]` extra; where libewf is absent, E01 is exercised
against a mocked `pyewf.handle` (per RESEARCH.md A3 / environment caveat).

---

## Sampling Rate

- **After every task commit:** Run `pytest -q`
- **After every plan wave:** Run `pytest -q --maxfail=1`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

*Reconciled to the final 5-plan structure (01-00 scaffold, 01-01 case store + audit, 01-02 image seam + hashing + RO guarantee, 01-03 safe-extract jail, 01-04 ingest orchestrator + CLI).*

| Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-00 | 0 | scaffold | — | src layout + pyproject + pytest import OK; failing e2e smoke pins target | unit | `pytest -q` | ❌ W0 | ⬜ pending |
| 01-02 | 1 | INGEST-01 | T-1-01 | raw/dd image opened read-only via pytsk3 (never mounted) | unit | `pytest -q tests/test_image.py` | ❌ W0 | ⬜ pending |
| 01-02 | 1 | INGEST-01 | T-1-01 | E01 opened via EWFImgInfo adapter (mocked pyewf) | unit | `pytest -q tests/test_ewf_adapter.py` | ❌ W0 | ⬜ pending |
| 01-02 | 1 | INGEST-02 | T-1-02 | MD5+SHA-256 single-pass; acquisition mismatch fails loudly (non-zero exit) | unit | `pytest -q tests/test_hashing.py` | ❌ W0 | ⬜ pending |
| 01-02 | 1 | INGEST-03 | T-1-03 | source never written/mounted; re-verify hash at end; output only in case dir | unit | `pytest -q tests/test_readonly_guarantee.py` | ❌ W0 | ⬜ pending |
| 01-03 | 1 | INGEST-04 | T-1-04 | safe_extract rejects Zip Slip / symlink escape / bomb on fixture | unit | `pytest -q tests/test_safe_extract.py` | ❌ W0 | ⬜ pending |
| 01-01 | 1 | REPORT-01 | T-1-05 | case/COC metadata persisted in SQLite case store | unit | `pytest -q tests/test_case_store.py` | ❌ W0 | ⬜ pending |
| 01-01 | 1 | REPORT-02 | T-1-06 | append-only JSONL audit log written only to case dir, UTC events | unit | `pytest -q tests/test_audit_log.py` | ❌ W0 | ⬜ pending |
| 01-04 | 2 | INGEST-01..03 + REPORT-01/02 | T-1-01..06 | `run_ingest` orchestration: RO open, hash + re-verify, COC row, JSONL audit, output confined to case dir | integration | `pytest -q tests/test_ingest.py` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*
*Final test filenames owned by the listed plan's `files_modified`.*

---

## Wave 0 Requirements

- [ ] `pyproject.toml` — hatchling backend, src layout, pytest config, optional `[ewf]`/`[timeline]` extras
- [ ] `pytest` + `pytest`-based test tree (`tests/`) installed and importable
- [ ] `tests/conftest.py` — shared fixtures: synthetic raw image (<1 MB committed fixture), malicious-archive fixtures (Zip Slip / symlink / bomb), tmp_path case dir
- [ ] `tests/fixtures/` — pre-built tiny raw image + malicious tar/zip fixtures (avoids CI `mkfs`/`mtools` dependency, per RESEARCH.md A2)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real E01 ingest on a host with libewf installed | INGEST-01 | CI host lacks `libewf-dev`; adapter is mock-tested in CI | On a libewf-equipped host: `pip install .[ewf]` then `pyautopsy ingest sample.E01 --case /tmp/c --examiner me --evidence-id E1`; confirm case store + audit log created |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (plan 01-00 stands up pytest + tests/ + fixtures)
- [x] No watch-mode flags
- [x] Feedback latency < 15s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-05-30 (plan-check confirmed Wave 0 coverage; `wave_0_complete` flips true after execution)
