---
phase: 04-deleted-recovery-known-file-filtering
plan: 03
subsystem: analyze-integration
tags: [recovery, filtering, determinism, read-only, honesty, cli]
requires: ["04-01", "04-02"]
provides:
  - "opt-in recover+filter steps in run_analyze (D-40)"
  - "analyze --recover / --nsrl / --hash-set-allow / --hash-set-block flags"
  - "recover --nsrl / --hash-set-* post-recovery filter pass"
  - "conditional honest _MVP_LIMITATIONS disclaimer"
  - "reproducibility + read-only-after-recover integration gates"
affects:
  - src/pyautopsy/core/analyze.py
  - src/pyautopsy/cli/main.py
  - src/pyautopsy/report/assemble.py
tech-stack:
  added: []
  patterns:
    - "opt-in pipeline steps gated on supplied input (default path byte-stable)"
    - "conditional report copy rebuilt from what actually ran (no over/under-claim)"
    - "paired --hash-set-allow/--hash-set-block CLI options carry list sense"
key-files:
  created:
    - .planning/phases/04-deleted-recovery-known-file-filtering/04-03-SUMMARY.md
  modified:
    - src/pyautopsy/core/analyze.py
    - src/pyautopsy/cli/main.py
    - src/pyautopsy/report/assemble.py
    - tests/test_reproducibility.py
    - tests/test_readonly_guarantee.py
decisions:
  - "Recovery runs BEFORE filtering inside run_analyze so the filter pass annotates recovered rows too (knownfiles reads allocated + recovered alike)"
  - "Filtering opt-in is triggered by nsrl_db OR any hash-set; recovery opt-in by an explicit --recover flag (D-40)"
  - "MVP-limitations disclaimer returns the verbatim Phase-3 string when nothing ran (keeps default report byte-identical) and is rebuilt only when recovery/filtering ran (D-28/D-32)"
  - "CLI carries list sense via paired --hash-set-allow/--hash-set-block options (deterministic order: all allow then all block, D-41)"
metrics:
  duration: ~30min
  completed: 2026-05-31
  tasks: 2
  files: 5
---

# Phase 4 Plan 03: Opt-in recover+filter analyze integration Summary

Wired deleted-file recovery and known-file filtering into `run_analyze` as
opt-in steps (D-40), added the remaining CLI flags on both `analyze` and
`recover`, made the report's `_MVP_LIMITATIONS` disclaimer conditional/honest,
and locked CLI-02/D-40/D-41/D-42 with three new integration tests — closing the
phase end-to-end with a default `analyze` that stays Phase-3 byte-identical.

## What was built

**Task 1 — opt-in wiring + flags + honesty (commit a417759)**
- `core/analyze.py`: `run_analyze` gains `recover`, `nsrl_db`, `hash_sets`
  params. Recovery (`run_recover`) and filtering (`run_filter`) splice between
  the walk and the timeline/report build, each gated on its input. Recovery
  runs before filtering so the filter pass annotates recovered rows too.
  `AnalyzeResult` + the `analyze.start`/`analyze.end` audit events gain
  `files_recovered`/`known_matches` (analytical counts, no wall-clock). With no
  inputs, the pipeline is unchanged and the report body byte-identical.
- `report/assemble.py`: new `_mvp_limitations(recovery_ran, filtering_ran)`
  helper. Returns the verbatim `_MVP_LIMITATIONS` string when neither ran (so
  the default report stays byte-identical to the Phase-3 baseline), and rebuilds
  the disclaimer honestly when recovery/filtering ran — no longer denying a
  capability that ran, carrying its caveat (ext4 pointer-zeroing / carving
  deferred CARVE-01; NSRL = examiner noise reduction, not adjudication), and no
  good/bad language (D-32). `assemble_report_body` threads two new flags through.
- `cli/main.py`: `--recover`/`--nsrl`/`--hash-set-allow`/`--hash-set-block` on
  `analyze`; `--nsrl`/`--hash-set-allow`/`--hash-set-block` on `recover` (which
  now runs a post-recovery filter pass when those are supplied). A `_hash_sets`
  helper pairs each list path with its allow/block sense in deterministic order.

**Task 2 — integration gates (commit 1ecbae6)**
- `tests/test_reproducibility.py`: `test_recover_filter_reproducible` (two
  `analyze --recover --nsrl --hash-set-allow` runs on the NTFS resident fixture
  → byte-identical `report.json` AND identical `recovered/` filename set; custom
  allow-list matches the recovered row) and `test_default_analyze_unchanged`
  (plain `analyze` byte-identical across runs, verbatim default disclaimer, zero
  recovered/known counts).
- `tests/test_readonly_guarantee.py`: `test_recover_does_not_write_source`
  (source `st_mtime_ns`/`st_size` unchanged after ingest+walk+recover; recovered
  bytes confined to the case dir; not-mounted guard re-assertable; Phase-1
  re-verify still runs).

## How it works

The report body already read recovered/orphan/known rows from the store
unconditionally (empty lists when nothing ran), so default determinism was
preserved for free — the only honesty-sensitive surface was the static
`_MVP_LIMITATIONS` string, which is now conditional. Opt-in gating lives in
`run_analyze`: `filter_requested = nsrl_db is not None or len(hash_sets) > 0`,
and `recover` is its own boolean. The CLI's paired allow/block options avoid a
brittle `path:sense` parse while keeping list sense explicit and order stable.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Test correctness] NTFS resident file recovers as an orphan, not a normal recovered entry**
- **Found during:** Task 2 (`test_recover_filter_reproducible` first run)
- **Issue:** The plan's sanity assertion assumed `recovered.count >= 1`, but the
  NTFS resident-deleted fixture's single recovered file has a gone parent and is
  classified an orphan (`recovered.count == 0`, `orphans.count == 1`) — the
  RECOV-02 separate-orphan-list behaviour established in 04-01.
- **Fix:** Assert on `recovered.count + orphans.count >= 1` instead; the custom
  allow-list still matches the recovered (orphan) row, so the recover+filter
  path is provably exercised (not a vacuous pass).
- **Files modified:** tests/test_reproducibility.py
- **Commit:** 1ecbae6

The plan's suggested `--hash-set` `path:sense` parsing was implemented as paired
`--hash-set-allow`/`--hash-set-block` options (the plan listed this as an
explicit alternative) — cleaner validation via Typer `exists=True` per option.

## Verification

- `python -m pytest tests/test_reproducibility.py tests/test_readonly_guarantee.py -x -q` → 12 passed (incl. the 3 new tests)
- `python -m pytest -q` → 184 passed (181 baseline + 3 new; no regressions)
- `python -m pytest tests/test_seam_allowlist.py -x -q` → 2 passed (analyze imports no pytsk3)
- `ruff check` clean; `mypy src` clean
- `analyze --help` shows `--recover`/`--nsrl`/`--hash-set-allow`/`--hash-set-block`; `recover --help` shows `--nsrl`/`--hash-set-*`

## Known Stubs

None. All wired sections are fed by real store rows; opt-in steps run real
orchestrators.

## Self-Check: PASSED

All 5 modified files + the SUMMARY exist; all 3 commits (a417759, 1ecbae6, 1a62ebe) are present in git history.
