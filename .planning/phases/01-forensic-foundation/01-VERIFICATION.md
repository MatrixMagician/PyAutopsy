---
phase: 01-forensic-foundation
verified: 2026-05-30T17:30:00Z
status: passed
score: 5/5 success criteria verified (24/24 plan truths)
overrides_applied: 0
mode: mvp
re_verification:
  previous_status: none
human_verification:
  - test: "Real E01 ingest on a host with libewf installed"
    expected: "`pip install .[ewf]` then `pyautopsy ingest sample.E01 ...` creates case store + audit log; EWFImgInfo delegates read/get_size/close to a live pyewf.handle"
    why_human: "This CI/dev host has no libewf/pyewf (confirmed: `import pyewf` raises ImportError; pytsk3 is present). The E01 adapter is real code exercised against a mocked pyewf.handle in CI. Per 01-VALIDATION.md this is the single documented Manual-Only verification — an accepted, documented arrangement, not a stub. Native-library confirmation requires real hardware/libs."
---

# Phase 1: Forensic Foundation Verification Report

**Phase Goal:** An examiner can ingest a raw/dd or E01 image entirely read-only, prove the source was never modified, and have every action recorded — establishing the integrity spine all later analysis writes into.
**Verified:** 2026-05-30T17:30:00Z
**Status:** passed (with 1 documented manual-only E01-native check routed to human)
**Re-verification:** No — initial verification
**Mode:** mvp

## Goal Achievement

This phase is MVP mode but its ROADMAP goal is a goal statement (not strict User Story form) backed by 5 explicit Success Criteria. Verification is goal-backward against those 5 SCs, merged with the 24 plan-frontmatter truths across the 5 plans. The forensic-soundness guarantees were verified to be **structurally real in the code**, not merely claimed — including direct confirmation that all 3 Critical + 7 Warning review fixes are present.

### Observable Truths (ROADMAP Success Criteria)

| # | Truth (Success Criterion) | Status | Evidence |
|---|---------|--------|----------|
| 1 | Examiner runs `pyautopsy ingest <image> --case ...` on raw/dd (or E01) and a SQLite case store is created with image opened read-only, never mounted | ✓ VERIFIED | Live run produced `/tmp/verify_case/case.db` + `cases`/`evidence_sources` rows; `image.py` opens via `pytsk3.Img_Info` byte-layer, module docstring + code have no mount/losetup/write path (line 22, 271); `assert_source_not_mounted` guard runs twice (ingest.py:167,199). E01 via `EWFImgInfo(pytsk3.Img_Info)` adapter (mock-tested; native libs absent → human item). |
| 2 | MD5 + SHA-256 computed, compared to supplied acquisition hash, re-verified at end of run, failing loudly on mismatch | ✓ VERIFIED | `hash_image` single streaming pass (integrity.py:120-164) with **truncation guard `if offset != total: raise`** (CR-02 fix, lines 158-163); `verify_acquisition` PASS/FAIL + hex validation (WR-07 fix, lines 197-203); `reverify` (lines 213-240); live audit chain shows `ingest.reverify outcome=PASS`. Tests test_ingest.py:235,257 assert mismatch → IntegrityError + FAIL audit. |
| 3 | Case/COC metadata (case ID, examiner, evidence ID, acquisition source, tool + TSK versions, timestamps) recorded in case store | ✓ VERIFIED | Live `cases` row: (1,'E-VERIFY','verifier','2026-05-30T17:29:31+00:00','0.1.0'); `evidence_sources` row: (1,1,'E-VERIFY','raw',sha256,65536,'4.15.0',acquired_utc). schema.sql typed columns + JSON `attributes` (D-02). Two COC inserts now **atomic via `store.transaction()`** with rollback (WR-01 fix, store.py:149-177). |
| 4 | Append-only audit log records inputs, hashes, parameters, versions, start/end times, errors — written only to the separate case directory | ✓ VERIFIED | `audit/log.py` O_APPEND+fsync (line 27,113), path confined to case dir via `_is_within` + `AuditPathError` (lines 52-57). Live `logs/audit.jsonl`: 8-event UTC chain start→write_guard→case_init→write_guard_recheck→open→hash→reverify(PASS)→end(SUCCESS). **Terminal FAIL event on any failed run via `except Exception` (CR-03 fix, ingest.py:258-268)**; tested test_ingest.py:277. |
| 5 | safe_extract rejects Zip Slip, symlink escape, decompression bombs (size/ratio/depth/count) on a malicious-archive fixture | ✓ VERIFIED | `safe_extract.py` confinement (`_confined_target` realpath), symlink/device refusal (tar+zip), bomb caps. **Tar ratio cap now enforced at archive scope (WR-03 fix, lines 244,347-352)** and **escape compare normalized (WR-04 fix, `_normalized_member_name`, lines 198-207,298-304)**. 25 tests incl. ratio-bomb tar (test_safe_extract.py:249) all green; nothing written outside jail (`_no_escape`). |

**Score:** 5/5 success criteria verified.

### Plan-Frontmatter Truths (24 total)

All 24 must_have truths across plans 01-00..01-04 map to verified artifacts and behaviors above and to passing per-area test files (test_image 14, test_ewf_adapter 4, test_integrity 21, test_readonly_guarantee 5, test_safe_extract 25, test_case_store 13, test_audit_log 6, test_ingest 16, test_reproducibility 2, test_cli_smoke 6, test_timeutil 8). No truth unaccounted for.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `pyproject.toml` | hatchling, src layout, pytest, [ewf] extra, pins | ✓ VERIFIED | `[project.scripts]` exposes `pyautopsy`; lint/type config present |
| `src/pyautopsy/util/timeutil.py` | tz-aware UTC helpers | ✓ VERIFIED | Single sanctioned timestamp source; used by store + audit |
| `src/pyautopsy/case/schema.sql` | typed columns + JSON attributes | ✓ VERIFIED | cases/evidence_sources/run_log, FK, attributes TEXT |
| `src/pyautopsy/case/store.py` | CaseStore + atomic inserts | ✓ VERIFIED | `transaction()` rollback; `cur.lastrowid is None` check (WR-06) |
| `src/pyautopsy/case/models.py` | Case/EvidenceSource/AuditEvent | ✓ VERIFIED | dataclasses, UTC fields |
| `src/pyautopsy/audit/log.py` | append-only JSONL, confined | ✓ VERIFIED | O_APPEND+fsync, `_is_within` confinement |
| `src/pyautopsy/evidence/image.py` | ONLY pytsk3/pyewf importer, RO open + EWFImgInfo | ✓ VERIFIED | raw via Img_Info; lazy pyewf import; no write/mount path |
| `src/pyautopsy/evidence/integrity.py` | single-pass hash, compare, reverify, mount guard | ✓ VERIFIED | CR-01/CR-02/WR-07 fixes all present |
| `src/pyautopsy/util/safe_extract.py` | hardened jail | ✓ VERIFIED | WR-03/WR-04 fixes present; 25 tests |
| `src/pyautopsy/core/ingest.py` | orchestrator | ✓ VERIFIED | CR-03/WR-01/WR-02/WR-05 fixes present |
| `src/pyautopsy/cli/main.py` | Typer ingest cmd, non-zero exit | ✓ VERIFIED | Catches IntegrityError/MountedSourceError/IngestError/ImageOpenError → exit code (line 110-112) |

### Key Link Verification

| From | To | Via | Status |
|------|-----|-----|--------|
| cli/main.py | core/ingest.py | `run_ingest` call | ✓ WIRED |
| core/ingest.py | evidence/integrity.py | hash + compare + reverify | ✓ WIRED |
| core/ingest.py | case/store.py | CaseStore + insert_evidence_source in transaction | ✓ WIRED |
| core/ingest.py | audit/log.py | AuditLog every action incl. FAIL | ✓ WIRED |
| case/store.py | schema.sql | executescript on init | ✓ WIRED |
| audit/log.py | logs/audit.jsonl | O_APPEND under case dir | ✓ WIRED |
| evidence/integrity.py | evidence/image.py | read(offset,size) handle | ✓ WIRED |
| integrity.py | /proc/mounts | mounted-source refusal | ✓ WIRED |

### Data-Flow Trace (Level 4)

| Artifact | Data | Source | Real Data | Status |
|----------|------|--------|-----------|--------|
| case.db cases/evidence_sources | COC rows | live `run_ingest` over tiny_raw.dd | Yes — real sha256/md5/byte_size/TSK ver | ✓ FLOWING |
| logs/audit.jsonl | audit events | `AuditLog.write` per pipeline step | Yes — 8 real UTC events, no placeholders | ✓ FLOWING |
| IngestResult (CLI output) | digests/size/type | hash_image over real handle | Yes — sha256 matches DB + CLI | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Live raw ingest exits 0, prints summary | `pyautopsy ingest tiny_raw.dd ...` | exit 0, "ingest complete" + real sha256 | ✓ PASS |
| case.db has COC rows | sqlite query cases/evidence_sources | 1 case + 1 evidence row, populated | ✓ PASS |
| audit.jsonl is full UTC chain | parse jsonl | 8 ordered events, all `+00:00` ts | ✓ PASS |
| Full test suite | `pytest -q` | 120 passed | ✓ PASS |
| Lint | `ruff check src tests` | No issues | ✓ PASS |
| Types | `mypy src` | No issues | ✓ PASS |

### Review-Fix Confirmation (3 Critical + 7 Warning)

| ID | Fix | Commit | Present in code? |
|----|-----|--------|------------------|
| CR-01 | non-ASCII mountpoint guard (`_unescape_mount_field`, octal-only) | 75cc38d | ✓ integrity.py:251-269; test:170-200 |
| CR-02 | truncated-image guard `if offset != total: raise` | 75cc38d | ✓ integrity.py:158-163; test:105-117 |
| CR-03 | terminal FAIL audit on any failed ingest | f4fc4b3 | ✓ ingest.py:258-268; test:277 |
| WR-01 | atomic COC inserts (`transaction()` + rollback) | 05635dd/f4fc4b3 | ✓ store.py:149-177; ingest.py:188 |
| WR-02 | re-check mount guard after open | f4fc4b3 | ✓ ingest.py:199 (audit write_guard_recheck) |
| WR-03 | tar compression-ratio cap (archive scope) | 993bd76 | ✓ safe_extract.py:244,347-352; test:249 |
| WR-04 | normalized escape compare | 993bd76 | ✓ safe_extract.py:198-207,298-304 |
| WR-05 | audit malformed acquisition hash before propagate | f4fc4b3 | ✓ ingest.py:303-313 |
| WR-06 | remove dead try/except, `lastrowid is None` check | 05635dd | ✓ store.py:217-218 |
| WR-07 | hex validation in verify_acquisition | 75cc38d | ✓ integrity.py:197-203 |

All 10 fixes are real in the code, not merely claimed.

### Requirements Coverage

Every phase requirement ID from PLAN frontmatter cross-referenced against REQUIREMENTS.md (Phase 1 maps exactly INGEST-01..04, REPORT-01, REPORT-02 — 6 IDs; no orphans, no extras).

| Requirement | Source Plan(s) | Description | Status | Evidence |
|-------------|---------------|-------------|--------|----------|
| INGEST-01 | 01-00,01-02,01-04 | Ingest raw/dd + E01/EWF | ✓ SATISFIED | raw verified live; E01 adapter real, mock-tested (native confirm → human) |
| INGEST-02 | 01-00,01-02,01-04 | MD5+SHA-256 + acquisition compare | ✓ SATISFIED | single-pass hash + truncation guard + verify_acquisition; tested |
| INGEST-03 | 01-00,01-02,01-04 | Never modified — RO, never mounted, end-of-run reverify | ✓ SATISFIED | no write/mount path; double mount guard; reverify PASS live |
| INGEST-04 | 01-00,01-03 | Safe extract rejects Zip Slip / bombs | ✓ SATISFIED | safe_extract jail, 25 tests, WR-03/WR-04 fixes |
| REPORT-01 | 01-00,01-01,01-04 | COC metadata in case store | ✓ SATISFIED | live cases + evidence_sources rows, atomic |
| REPORT-02 | 01-00,01-01,01-04 | Append-only audit log incl. errors | ✓ SATISFIED | JSONL confined, full UTC chain, terminal FAIL event |

No ORPHANED requirements. REQUIREMENTS.md traceability table marks all 6 Complete; verified consistent.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none) | — | No TBD/FIXME/XXX/HACK/PLACEHOLDER in src/ | — | Clean — completion is auditable |

No stubs: every grep-flagged empty-default (e.g. `attributes DEFAULT '{}'`) is a legitimate schema/initial value overwritten by real data flow, not a hollow render. safe_extract's lack of an in-phase caller is documented and intentional (security gate locked early; consumers arrive Phase 5).

### Human Verification Required

#### 1. Real E01 ingest on a libewf-equipped host

**Test:** On a host with `libewf` installed: `pip install .[ewf]` then `pyautopsy ingest sample.E01 --case /tmp/c --examiner me --evidence-id E1`; confirm case store + audit log created and the EWFImgInfo adapter delegates read/get_size/close to a live `pyewf.handle`.
**Expected:** Same case.db + audit chain as the raw path, with `image_type='ewf'`.
**Why human:** This host has no libewf/pyewf (confirmed `import pyewf` → ImportError; pytsk3 present). The adapter is real code exercised against a mocked pyewf.handle in CI; per 01-VALIDATION.md "Manual-Only Verifications" this is the single accepted, documented arrangement — not a stub. Native-library confirmation needs real libs/hardware.

### Gaps Summary

No gaps. All 5 ROADMAP success criteria and all 24 plan truths are verified in the codebase. The forensic-soundness spine is structurally real: read-only byte-layer open with no write/mount path, double mount-guard, single-pass hashing with a loud truncation guard, end-of-run reverify, atomic COC persistence, and a confined append-only audit log that records a terminal FAIL on any failed run. All 3 Critical + 7 Warning review findings were independently confirmed fixed in the code (not just claimed). 120 tests pass; ruff and mypy clean; a live raw ingest produced a real case.db + full UTC audit chain.

The only non-automated item is real-E01-on-real-libewf, which is the project's documented Manual-Only verification and the sole reason status carries a human item rather than a bare `passed`. Automated coverage (raw ingest + mocked E01 + malicious fixtures) fully drives the soundness verdict.

---

_Verified: 2026-05-30T17:30:00Z_
_Verifier: Claude (gsd-verifier)_
