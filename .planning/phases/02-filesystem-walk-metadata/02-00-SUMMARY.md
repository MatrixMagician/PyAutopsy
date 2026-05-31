---
phase: 02-filesystem-walk-metadata
plan: 00
subsystem: testing
tags: [pytsk3, python-magic, libmagic, ext4, ntfs, fat32, pytest, fixtures, tdd, forensics]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: evidence/image.py byte-layer seam (open_image), tiny_raw.dd committed-fixture pattern, integrity.py single-pass hasher, timeutil.iso_utc/from_epoch_utc
provides:
  - python-magic==0.4.27 dependency + evidence/filetype.py content-typing wrapper with binding-collision guard
  - committed tiny ext4/NTFS/FAT32/partitioned fixture images (CI needs no mkfs)
  - tests/fixtures/make_fixtures.py FS builders + ground-truth constants
  - conftest tiny_ext4_image/tiny_ntfs_image/tiny_fat32_image/tiny_partitioned_image fixtures
  - executable D-14 seam allowlist test (was convention-only)
  - RED test stubs for META-01..05 + D-20 + read-only-after-walk (Nyquist scaffold)
affects: [02-01-filesystem-seam, 02-02-walk-orchestrator, 02-03-cli-walk]

# Tech tracking
tech-stack:
  added: [python-magic==0.4.27]
  patterns:
    - "Content-signature typing isolated in evidence/filetype.py (NOT a pytsk3 seam) with import-time binding guard"
    - "Committed FS fixture images built once with host mkfs tools; ground truth as module constants for exact-count assertions"
    - "Executable architecture guard: regex-scan src/ for native imports, fail if outside the allowlist"
    - "Permitted-if-present allowlist so the gate is green before AND after the seam file exists"

key-files:
  created:
    - src/pyautopsy/evidence/filetype.py
    - tests/fixtures/tiny_ext4.img
    - tests/fixtures/tiny_ntfs.img
    - tests/fixtures/tiny_fat32.img
    - tests/fixtures/tiny_partitioned.img
    - tests/test_seam_allowlist.py
    - tests/test_filesystem.py
    - tests/test_walk.py
  modified:
    - pyproject.toml
    - tests/fixtures/make_fixtures.py
    - tests/conftest.py
    - tests/test_readonly_guarantee.py

key-decisions:
  - "file_type(read_head, size) takes a (offset,size)->bytes callable, not a TSK File, so the orchestrator stays testable with a fake and magic stays isolated"
  - "filetype.py guards the binding at IMPORT time (module-level hasattr) so the wrong magic fails fast, not deep inside the walk"
  - "Committed FS images compress to ~70KB each in git despite 1-74MB apparent sizes; FAT32 kept at 64MiB because mkfs.fat -F 32 needs it"
  - "NTFS fixture relies on system files for the walk path (ntfscp absent on host); ext4 carries the known regular file + the deleted entry the META tests need"
  - "Seam allowlist is permitted-if-present for filesystem.py: green today with only image.py, stays green once Plan 02-01 adds the FS seam"

patterns-established:
  - "Import-time native-binding collision guard with actionable ImportError (mirrors image.py pyewf hint)"
  - "Ground-truth-as-constants in make_fixtures.py enabling exact-count Nyquist assertions"
  - "Executable D-14 seam allowlist arch guard (replaces the convention-only grep gate)"

requirements-completed: [META-01, META-02, META-03, META-04, META-05]

# Metrics
duration: 7min
completed: 2026-05-31
---

# Phase 2 Plan 00: Wave 0 Scaffold Summary

**Test-first Wave-0 scaffold for the filesystem walk: python-magic==0.4.27 + a binding-guarded `filetype.py`, four committed ext4/NTFS/FAT32/partitioned fixture images, an executable D-14 seam allowlist gate, and RED META-01..05 + D-20 + read-only-after-walk stubs.**

## Performance

- **Duration:** ~7 min
- **Started:** 2026-05-31T10:32Z
- **Completed:** 2026-05-31T10:39Z
- **Tasks:** 3
- **Files created/modified:** 12

## Accomplishments
- `python-magic==0.4.27` declared in `[project.dependencies]`; `evidence/filetype.py` content-typing wrapper with an import-time `hasattr(magic, "from_buffer")` guard that raises an actionable `ImportError` if `file-magic` shadows `python-magic` (Pitfall 1, T-2-00-MAGIC mitigated). It is NOT a pytsk3 seam (0 pytsk3 imports per D-14/D-19).
- Four tiny filesystem fixture images built and committed: ext4 (one known file + a real DELETED entry + uid/gid/mode), NTFS (system files), FAT32 (local-time test, 64 MiB), and a partitioned FAT+ext4 image (D-15 volume-offset test). All open via the Phase 1 `open_image` seam AND as filesystems via pytsk3 `FS_Info`/`Volume_Info` (verified).
- `make_fixtures.py` builders + ground-truth constants (file name/content/uid/gid/mode, deleted-entry name) so the META tests can assert exact counts/values — the Nyquist "every file" signal. `conftest.py` exposes the four `*_image` fixtures.
- `test_seam_allowlist.py` turns the D-14 seam rule into an EXECUTABLE gate (was convention-only): it fails if any file outside `{evidence/image.py, evidence/filesystem.py}` imports pytsk3/pyewf. Green today; stays green once Plan 02-01 adds `filesystem.py`.
- RED stubs laid down for META-01..05 + D-20 (`test_walk.py`), the FS seam (`test_filesystem.py`), and read-only-after-walk (`test_readonly_guarantee.py`) — all collected, none skipped, all the exact node IDs from the 02-RESEARCH/02-VALIDATION test map.

## Task Commits

Each task was committed atomically:

1. **Task 1: python-magic dependency + filetype.py binding-collision guard** - `50facc0` (feat)
2. **Task 2: build + commit ext4/NTFS/FAT32/partitioned fixtures + conftest fixtures** - `c6884a1` (test)
3. **Task 3: executable D-14 seam allowlist test + RED META/D-20/read-only stubs** - `449f621` (test)

## Files Created/Modified
- `pyproject.toml` - added `python-magic==0.4.27` to `[project.dependencies]`
- `src/pyautopsy/evidence/filetype.py` - content-signature typing wrapper, import-time binding guard, `file_type(read_head, size)`
- `tests/fixtures/make_fixtures.py` - `build_tiny_ext4_image`/`build_tiny_fat32_image`/`build_tiny_ntfs_image`/`build_partitioned_image` + ground-truth constants + `main()` regenerates all
- `tests/fixtures/tiny_ext4.img`, `tiny_ntfs.img`, `tiny_fat32.img`, `tiny_partitioned.img` - committed FS fixture images
- `tests/conftest.py` - four committed-FS-image fixtures mirroring `tiny_raw_image`
- `tests/test_seam_allowlist.py` - executable D-14 native-seam allowlist arch guard
- `tests/test_filesystem.py` - RED FS-seam stubs (volume enumeration, bare-FS fallback, fs-type detection, recursion correctness)
- `tests/test_walk.py` - RED META-01..05 + D-20 orchestrator stubs
- `tests/test_readonly_guarantee.py` - added RED `test_source_unchanged_after_walk`

## Decisions Made
- `file_type` takes a head-reader callable + size (not a TSK `File`) so `magic` stays isolated and the orchestrator/tests use a fake — see frontmatter key-decisions for the full list.
- The committed images compress to ~70 KB each in git; the FAT32 64 MiB apparent size is required by `mkfs.fat -F 32` and is harmless in the repo.

## Deviations from Plan
None - plan executed exactly as written.

The plan's Task 1 instructed `pip install -e .` and `pip uninstall -y file-magic` "if present". On this host `python-magic==0.4.27` was already installed and already wins the import (its `magic/__init__.py` package shadows the single-file `file-magic`), so `from_buffer` is present and the guard passes. `file-magic 0.4.0` remains installed but is not shadowing; no uninstall was necessary and none was performed (uninstalling a host package is out of scope for a worktree executor). This is normal flow, not a deviation.

## Issues Encountered
- The editable install initially resolved `pyautopsy` to the MAIN repo source tree (not the worktree), so a plain `from pyautopsy.evidence import filetype` could not see the new module. Re-ran `pip install -e .` inside the worktree so imports resolve to the worktree; pytest already uses `pythonpath=["src"]` which points at the worktree regardless. All verification then passed.

## TDD Gate Compliance
This is a `type: execute` Wave-0 *scaffold* plan, not a `type: tdd` feature plan: it deliberately lays down RED tests with no implementation (the implementation lands in Plans 02-01/02/03). The 12 failing stubs are the intended RED state, the seam allowlist + binding guard are green, and the pre-existing 120-test suite stays green (now 122 with the seam allowlist). No RED→GREEN gate sequence applies to this plan.

## Next Phase Readiness
- Wave-0 infrastructure complete: green-able RED targets exist for every META-01..05 + D-20 + read-only requirement; the ~15s sampling command (`pytest tests/test_filesystem.py tests/test_walk.py -x`) works.
- Plan 02-01 can now add `src/pyautopsy/evidence/filesystem.py` (the FS seam) — the allowlist test already permits it and will turn the `test_filesystem.py` stubs green.
- `nyquist_compliant: true` is now achievable (the validation infra exists and fails RED as designed).
- Note for downstream plans: the NTFS fixture has no user-written regular file (host lacks `ntfscp`); META tests that need a known user file should target the ext4/FAT32 fixtures, or Plan 02-01 can add a file via an alternative tool if needed.

## Self-Check: PASSED

All created files verified on disk (filetype.py, four fixture images, three test files, this SUMMARY) and all three task commits (`50facc0`, `c6884a1`, `449f621`) verified in git history.

---
*Phase: 02-filesystem-walk-metadata*
*Completed: 2026-05-31*
