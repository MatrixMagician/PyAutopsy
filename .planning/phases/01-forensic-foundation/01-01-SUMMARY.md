---
phase: 01-forensic-foundation
plan: 01
subsystem: case-store
tags: [sqlite, wal, foreign-keys, jsonl, audit-log, chain-of-custody, utc, blackboard-schema, dataclasses, append-only, fsync]

# Dependency graph
requires:
  - "01-00: src-layout pyautopsy package, __version__ single source of truth, UTC timeutil helper, case_dir fixture"
provides:
  - "pyautopsy.case.CaseStore — the single SQLite writer abstraction (create/open, WAL, foreign_keys, insert + round-trip reads)"
  - "case.db schema (cases, evidence_sources, run_log) — typed core columns + JSON attributes blackboard (D-02), every timestamp UTC ISO-8601"
  - "D-01 case directory layout (logs/, exports/, case.db) materialised by CaseStore.create"
  - "frozen Case/EvidenceSource/AuditEvent dataclasses with tz-aware UTC fields and heterogeneous attributes dicts"
  - "pyautopsy.audit.AuditLog — append-only, fsync-durable, deterministic JSONL audit writer confined to <case_dir>/logs/audit.jsonl"
affects: [01-02, 01-03, 01-04, evidence-image, integrity-hashing, safe-extract, cli, metadata-walk, findings]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "CaseStore is the sole DB writer abstraction — no raw SQL outside src/pyautopsy/case/store.py (ARCHITECTURE Pattern 1 / Internal Boundaries)"
    - "Typed core columns + JSON attributes TEXT on every table (D-02 blackboard) so later producers add rows, never migrations"
    - "WAL journal_mode + foreign_keys=ON on every case.db open (D-03, PITFALLS P3)"
    - "Append-only audit via os.open(O_WRONLY|O_CREAT|O_APPEND) + os.fsync; sort_keys=True for byte-identical reproducibility (PITFALLS P3/P12)"
    - "Audit log path always recomputed under <case_dir>/logs/ and confinement-checked; reserved action/ts fields rejected (T-1-01-A)"
    - "All timestamps via timeutil.iso_utc — single sanctioned source (D-10)"

key-files:
  created:
    - src/pyautopsy/case/__init__.py
    - src/pyautopsy/case/schema.sql
    - src/pyautopsy/case/models.py
    - src/pyautopsy/case/store.py
    - src/pyautopsy/audit/__init__.py
    - src/pyautopsy/audit/log.py
    - tests/test_case_store.py
    - tests/test_audit_log.py
  modified: []

key-decisions:
  - "run_log table doubles as the optional SQLite mirror target for the audit log (Claude's Discretion, D-09) — schema is present now; JSONL stays authoritative and is the only writer wired this plan."
  - "Tool version for the COC record reads importlib.metadata.version('pyautopsy') with a fallback to pyautopsy.__version__ so the store works from an uninstalled source checkout too."
  - "AuditLog rejects caller-supplied 'action'/'ts' keys rather than silently overwriting them — prevents a caller from shadowing the UTC stamp or the action name (tamper-evidence integrity)."
  - "attributes columns are NOT NULL DEFAULT '{}' and serialised with json.dumps(sort_keys=True) so the blackboard column is always valid JSON and deterministic."

patterns-established:
  - "Single DB writer seam (CaseStore) mirrors the single native seam from 01-00 — later phases get rows/tables through this class, never ad-hoc SQL."
  - "Every persisted timestamp column is asserted to end in '+00:00' by a dedicated test — UTC-everywhere is now enforced at the storage boundary, not just the helper."

requirements-completed: [REPORT-01, REPORT-02]

# Metrics
duration: 8min
completed: 2026-05-30
---

# Phase 1 Plan 01: SQLite Case Store & Append-Only Audit Log Summary

**Built the forensic-soundness spine: a `CaseStore` SQLite repository (WAL + foreign keys, typed-columns + JSON-`attributes` blackboard schema for `cases`/`evidence_sources`/`run_log`) that materialises the D-01 case directory layout and round-trips chain-of-custody metadata with UTC-everywhere timestamps, plus an append-only, fsync-durable, deterministically-ordered JSONL `AuditLog` confined to `<case_dir>/logs/` — delivering REPORT-01 and REPORT-02 with `pytest -q` green (24 passed, 1 xfailed).**

## Performance

- **Duration:** ~8 min
- **Tasks:** 2 completed
- **Files modified:** 8 created

## Accomplishments
- **Case store (REPORT-01, Task 1):** `src/pyautopsy/case/` — `schema.sql` defines `cases`, `evidence_sources` (FK→cases, indexed), and `run_log` (FK→cases, indexed), each with typed core columns plus a `attributes TEXT NOT NULL DEFAULT '{}'` JSON column (D-02). `CaseStore.create()` builds the `logs/`/`exports/`/`case.db` layout (D-01), opens WAL with `foreign_keys=ON` (D-03), and applies the schema via `executescript`. `insert_case`/`insert_evidence_source` plus `get_case`/`get_evidence_source` round-trip the COC models; the tool version is recorded via `importlib.metadata`. It is the only module containing SQL.
- **Audit log (REPORT-02, Task 2):** `src/pyautopsy/audit/log.py` — `AuditLog` appends one structured event per line to `<case_dir>/logs/audit.jsonl` using `os.open(O_WRONLY|O_CREAT|O_APPEND)` + `os.write` + `os.fsync`, never truncating. Events serialise with `sort_keys=True` (byte-identical repeats), each carries a UTC `ts` from `iso_utc` (D-10), the path is always recomputed under the case dir and confinement-checked (`AuditPathError`), and reserved `action`/`ts` keys are rejected.
- **Models:** frozen, `slots=True` `Case`/`EvidenceSource`/`AuditEvent` dataclasses with `str | None` hints, no mutable default args (`field(default_factory=dict)`), Google docstrings.
- **Tests:** 10 case-store tests (layout, pragmas, COC round-trip, UTC-column assertion, heterogeneous-attributes round-trip, FK enforcement, missing-row lookup) + 6 audit-log tests (two-writes-two-lines, UTC `ts` + field retention, deterministic byte-identical repeats, append-never-truncates, path-under-case-dir, reserved-field rejection).
- **Quality gates:** `ruff check` clean, `mypy src/pyautopsy/case src/pyautopsy/audit` clean (5 source files), full `pytest -q` → 24 passed, 1 xfailed (the 01-00 ingest smoke test stays xfail until 01-04).

## Task Commits

1. **Task 1: Case store — directory layout, schema, and repository (REPORT-01)** — `c0b0e27` (feat; test + impl together)
2. **Task 2: Append-only JSONL audit log (REPORT-02)** — `cd85d26` (feat; test + impl together)

**Plan metadata:** _(final docs commit — see below)_

## Files Created/Modified
- `src/pyautopsy/case/schema.sql` — `cases`, `evidence_sources`, `run_log` DDL; typed columns + JSON `attributes`; FK indexes.
- `src/pyautopsy/case/models.py` — frozen `Case`/`EvidenceSource`/`AuditEvent` dataclasses, tz-aware UTC string fields, heterogeneous `attributes` dicts.
- `src/pyautopsy/case/store.py` — `CaseStore` sole writer: `create`/`open`, WAL + foreign keys, insert/round-trip reads, `importlib.metadata` tool version with `__version__` fallback.
- `src/pyautopsy/case/__init__.py` — package exports (`Case`, `EvidenceSource`, `AuditEvent`, `CaseStore`).
- `src/pyautopsy/audit/log.py` — `AuditLog` + `AuditPathError`: O_APPEND/fsync JSONL writer, sorted keys, case-dir confinement, reserved-field guard.
- `src/pyautopsy/audit/__init__.py` — package exports (`AuditLog`, `AuditPathError`).
- `tests/test_case_store.py` — 10 case-store tests.
- `tests/test_audit_log.py` — 6 audit-log tests.

## Decisions Made
- **`run_log` as optional SQLite mirror target:** the schema includes `run_log` now (segregated run metadata per PITFALLS P3 and the optional audit mirror per D-09), but only the JSONL log is wired as a writer this plan — JSONL stays authoritative. The mirror can be turned on by a later phase without a migration.
- **Tool-version fallback:** `importlib.metadata.version('pyautopsy')` with a `PackageNotFoundError` fallback to `pyautopsy.__version__`, so the COC record is populated whether or not the dist is installed.
- **Reserved-field rejection in the audit writer:** callers cannot pass `action`/`ts` — this prevents shadowing the UTC stamp or the action name, a small but real tamper-evidence guarantee.

## Deviations from Plan

None — plan executed as written. (The package was editable-installed via `pip install -e .` so `importlib.metadata.version('pyautopsy')` resolves; this is dev-environment setup against the already-declared distribution, not a new dependency, and the store also works uninstalled via the `__version__` fallback.)

## Threat Model Coverage
- **T-1-05 (Repudiation, COC rows):** `cases` + `evidence_sources` persist examiner, evidence_id, acquisition path, image_type, sha256/md5, tsk_version, pyautopsy_version, and UTC timestamps — round-tripped by tests.
- **T-1-06 (Repudiation/Tampering, audit log):** append-only `O_APPEND` + `fsync` per event, deterministic sorted keys, written only under `<case_dir>/logs/`.
- **T-1-01-A (Tampering, path injection):** audit path always recomputed as `<case_dir>/logs/audit.jsonl` and confinement-checked; escape raises `AuditPathError`.
- **T-1-01-B (Information Disclosure):** all writes confined to the case dir; SQLite is a single hashable file; no network egress.

## Known Stubs
None. `run_log` exists in the schema but is intentionally unwired as an audit mirror this plan (JSONL is authoritative, D-09); this is a forward-compatible table, not a stub blocking REPORT-01/REPORT-02.

## Verification Evidence
- `pytest -q tests/test_case_store.py tests/test_audit_log.py` → 16 passed.
- Full `pytest -q` → 24 passed, 1 xfailed (`test_ingest_smoke`, the 01-04 Walking Skeleton target).
- `ruff check src/pyautopsy/case src/pyautopsy/audit tests/test_case_store.py tests/test_audit_log.py` → all checks passed.
- `mypy src/pyautopsy/case src/pyautopsy/audit` → success, no issues (5 source files).

## TDD Gate Compliance
Config `tdd_mode` is false, so separate RED/GREEN gate commits were not required. Both tasks nonetheless followed TDD: each test file was written first and confirmed to fail for the right reason (`ModuleNotFoundError: No module named 'pyautopsy.case'` / `'pyautopsy.audit'`) before implementation, then passed. Test + implementation were committed together per the 01-00 convention.

## Self-Check: PASSED
All 8 created files exist on disk; both task commits (`c0b0e27`, `cd85d26`) are present in git history.
