---
phase: 01-forensic-foundation
plan: 04
subsystem: core+cli
tags: [ingest, orchestrator, typer-cli, walking-skeleton, reproducibility, ingest-01, ingest-02, ingest-03, report-01, report-02, d-12, cli-02]

# Dependency graph
requires:
  - "01-00: scaffold, src layout, pyautopsy.__version__, tiny_raw.dd fixture, xfail(strict) ingest smoke test"
  - "01-01: CaseStore (create/insert_case/insert_evidence_source) + AuditLog (append) — COC persistence + audit"
  - "01-02: open_image (read-only raw/E01) + hash_image / verify_acquisition / reverify / assert_source_not_mounted"
provides:
  - "core/ingest.py::run_ingest — the forensic-spine orchestrator: read-only open -> case store -> COC/evidence rows -> single-pass MD5+SHA-256 -> optional acquisition compare -> append audit events (start->end) -> end-of-run source re-verify -> SUCCESS or loud non-zero on any integrity mismatch; all output confined to the case dir, source untouched"
  - "cli/main.py — Typer app: `pyautopsy ingest <image> --case <dir> --examiner <name> --evidence-id <id> [--acquisition-hash <hash>]` (D-12) + `pyautopsy --version`"
  - "Closed Walking Skeleton: a real raw/dd or E01 image -> defensible case store + audit log via one command"
affects: [02-filesystem-metadata, 03-timeline-report, 04-recovery-filtering, 05-log-timeline-search]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "orchestrator composes existing modules — no reimplementation of case store, audit, image, or integrity"
    - "audit event chain bookends the run (ingest.start ... ingest.end) with write_guard / case_init / open / hash / reverify events between"
    - "end-of-run source hash re-verify (D-08) — baseline captured at open, compared at end, mismatch is a loud non-zero exit"
    - "determinism (CLI-02): sort_keys JSONL, stable field ordering, recorded tool + libtsk versions; reproducibility test asserts byte-identical analytical fields across two runs"
    - "xfail(strict) smoke marker removed — the e2e test now asserts the real contract and fails loudly on regression"

key-files:
  created:
    - src/pyautopsy/core/__init__.py
    - src/pyautopsy/core/ingest.py
    - src/pyautopsy/cli/__init__.py
    - src/pyautopsy/cli/main.py
    - tests/test_ingest.py
    - tests/test_reproducibility.py
  modified:
    - tests/test_cli_smoke.py

key-decisions:
  - "run_ingest is the single orchestration entry point; the Typer command is a thin shell over it so the orchestration is testable without the CLI."
  - "Source hash baseline is captured at open and re-verified at end of run; any mismatch raises and exits non-zero (forensic soundness, D-08 / INGEST-03)."
  - "A wrong --acquisition-hash records a FAIL audit event and exits loudly non-zero rather than continuing (INGEST-02)."
  - "Reproducibility test runs ingest twice and asserts the analytical fields (hashes, sizes, ordering) are byte-identical, excluding wall-clock timestamps (CLI-02)."

requirements-completed: [INGEST-01, INGEST-02, INGEST-03, REPORT-01, REPORT-02]

# Metrics
duration: ~23min (executor stream-closed mid task-2; orchestrator closed out: verified, committed task-2, wrote SUMMARY, updated tracking)
completed: 2026-05-30
---

# Phase 1 Plan 04: Ingest Orchestrator + Typer CLI (Walking Skeleton Closeout) Summary

**Built `core/ingest.py::run_ingest` — the forensic-spine orchestrator that composes the Wave-0/Wave-1 components into one command: it opens a raw/dd or E01 image read-only (never mounted), creates the SQLite case store and records chain-of-custody + evidence rows, streams MD5+SHA-256 in a single pass, optionally compares a supplied acquisition hash (loud FAIL on mismatch), writes an append-only JSONL audit chain (`ingest.start → write_guard → case_init → open → hash → reverify → ingest.end`), and re-verifies the source hash at end of run — exiting 0 on success or loudly non-zero on any integrity violation. The `pyautopsy ingest` Typer CLI (D-12 signature) plus `pyautopsy --version` is a thin shell over it. The xfail(strict) Walking-Skeleton smoke test was flipped to assert the real contract, and a reproducibility test proves two runs yield byte-identical analytical fields. This closes the Phase-1 Walking Skeleton: image in → defensible case store + audit log out.**

## Performance

- **Duration:** ~23 min (the executor agent's stream closed unexpectedly mid task-2 after the implementation was written to disk and the suite was green; the orchestrator verified the on-disk work, ran the CLI end-to-end, committed task-2, and wrote this SUMMARY + tracking)
- **Completed:** 2026-05-30
- **Tasks:** 2 completed (task 1 committed by executor as `8727ab7`; task 2 committed during closeout as `15ab69a`)
- **Files:** 6 created, 1 modified

## Accomplishments

- `run_ingest` orchestrator wiring read-only open → case store → COC/evidence rows → single-pass hashing → audit chain → end-of-run re-verify.
- `pyautopsy ingest` Typer CLI matching the D-12 signature; `pyautopsy --version` → `pyautopsy 0.1.0`.
- Flipped the e2e ingest smoke test from `xfail(strict)` to a real passing contract.
- Added the reproducibility test (CLI-02 determinism).

## Verification

- `pytest -q` → **105 passed, 0 xfailed** (the previously-xfail smoke test now passes for real).
- Live end-to-end run on `tests/fixtures/tiny_raw.dd`: exit 0, produced `case.db` (tables `cases`, `evidence_sources`, `run_log`) + `logs/audit.jsonl` with the full UTC audit chain (`read_only: true`, `tsk_version: 4.15.0`, MD5+SHA-256, reverify PASS, end SUCCESS).
- `ruff check` / `mypy src` clean.

## Notes

- The executor agent terminated with an API socket-close after writing all task-2 files and turning the suite green (105 passed) but before committing task-2 / writing SUMMARY / updating tracking. Per the execute-phase completion-signal fallback, the orchestrator verified completion via filesystem + git + a live CLI run, then closed out manually rather than re-running the plan.
- `.planning/graphs/` and `graphify-out/` are graphmind tooling artifacts, left untracked.
- INGEST-04 (safe_extract jail) is delivered by plan 01-03; the raw-image ingest path does not expand archives, so the jail has no caller in Phase 1 (consumers arrive in Phase 5 log/archive parsing).
