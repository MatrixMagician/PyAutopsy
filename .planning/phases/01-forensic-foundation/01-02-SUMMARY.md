---
phase: 01-forensic-foundation
plan: 02
subsystem: evidence-image
tags: [pytsk3, pyewf, ewf-adapter, single-native-seam, read-only, md5, sha256, single-pass-hash, re-verify, mounted-source-guard, strenum]

# Dependency graph
requires:
  - "01-00: src-layout pyautopsy package, pinned pytsk3==20260520 + [ewf] extra, committed tiny_raw.dd fixture, tiny_raw_image fixture, ruff/mypy/pytest config"
provides:
  - "pyautopsy.evidence.image — the ONLY module importing pytsk3 (pyewf lazily); open_image() returns a read-only ImageHandle (raw via pytsk3.Img_Info, E01 via EWFImgInfo adapter) carrying size + detected format"
  - "EWFImgInfo(pytsk3.Img_Info) adapter delegating read(offset,size)/get_size()/close() to a pyewf.handle (canonical recipe)"
  - "ImageHandle plain value object + ReadableImage protocol — no pytsk3/pyewf type leaks past the seam (D-06)"
  - "tsk_version() — libtsk version string for the chain-of-custody record (probes pytsk3 VERSION attr, A1)"
  - "pyautopsy.evidence.integrity — single-pass md5+sha256 hash_image(); verify_acquisition() PASS/FAIL; reverify() end-of-run; assert_source_not_mounted() guard"
  - "IntegrityError (loud, non-zero-exit-worthy) + MountedSourceError + VerifyResult(.raise_for_status())"
affects: [01-04, ingest-orchestrator, cli, metadata-walk, deleted-recovery, timeline]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Single native seam: pytsk3/pyewf imported in exactly one module (evidence/image.py); grep gate enforces it (D-06, ARCHITECTURE AP-1)"
    - "pyewf imported lazily inside the E01 branch; ImportError -> actionable ImageOpenError (install pyautopsy[ewf] + libewf-dev), never a raw stack trace (PITFALLS P5)"
    - "EWFImgInfo(pytsk3.Img_Info) adapter (TSK_IMG_TYPE_EXTERNAL) — verbatim canonical recipe; only reads/seeks/size/close, never writes (INGEST-03)"
    - "Single streaming pass updates BOTH md5+sha256 over read(offset,size) (D-07) — never two passes; chunk size configurable, digest is chunk-invariant"
    - "Acquisition compare is case-insensitive hex, algorithm chosen by digest length (32->md5, 64->sha256); FAIL surfaces as a loud IntegrityError (D-08)"
    - "Mounted-source guard refuses a source path that IS a mountpoint (portable across hosts with separate /tmp,/home); injectable /proc/mounts table for testing (P1, ASVS V4)"
    - "mypy per-module override ignore_missing_imports for stub-less native bindings (pytsk3/pyewf), confined to the seam"
    - "StrEnum for ImageFormat (py311+)"

key-files:
  created:
    - src/pyautopsy/evidence/__init__.py
    - src/pyautopsy/evidence/image.py
    - src/pyautopsy/evidence/integrity.py
    - tests/test_image.py
    - tests/test_ewf_adapter.py
    - tests/test_integrity.py
    - tests/test_readonly_guarantee.py
  modified:
    - pyproject.toml

key-decisions:
  - "Mounted-source guard refuses only a source path that is ITSELF a mountpoint, not any file residing under a non-root mount — making it portable on hosts where /tmp/home are separate mounts while still catching the actionable 'loop-mounted evidence filesystem' case (P1)."
  - "Acquisition algorithm is selected by the supplied hash's hex length (32->md5, 64->sha256); a length matching neither raises IntegrityError so an uncomparable hash never silently passes."
  - "tsk_version() probes pytsk3 for a VERSION attribute (TSK_VERSION_STR present = '4.15.0') rather than asserting a hard-coded name, with an 'unknown' fallback (resolves 01-RESEARCH Open Question A1)."
  - "Added a mypy [[overrides]] block ignoring missing imports for pytsk3/pyewf only — they are stub-less C extensions confined to the single seam (D-06)."

patterns-established:
  - "The single native seam is now realised: evidence/image.py is the sole pytsk3/pyewf importer and the grep gate guards it; every downstream tier consumes the plain ReadableImage read interface."
  - "Forensic integrity is a pure-Python tier unit-tested with an in-memory fake handle AND the real fixture — no real image needed to prove correctness (mirrors the CaseStore/AuditLog seam discipline)."

requirements-completed: [INGEST-01, INGEST-02, INGEST-03]

# Metrics
duration: 9min
completed: 2026-05-30
---

# Phase 1 Plan 02: Native Evidence Seam & Integrity Layer Summary

**Built the load-bearing forensic boundary: `evidence/image.py` — the single module importing pytsk3 (pyewf lazily) — opens raw/dd via `pytsk3.Img_Info` and E01/EWF via the canonical `EWFImgInfo(pytsk3.Img_Info)` adapter, read-only at the byte layer and never mounting the source; and `evidence/integrity.py` streams MD5+SHA-256 in a single pass, compares to a supplied acquisition hash (PASS/FAIL), re-verifies at end of run, and hard-refuses a mounted source — delivering INGEST-01/02/03 with `pytest -q` green (62 passed, 1 xfailed), ruff + mypy clean, and the single-seam grep gate holding.**

## Performance

- **Duration:** ~9 min
- **Tasks:** 2 completed
- **Files modified:** 7 created, 1 modified

## Accomplishments
- **Single native seam (INGEST-01, Task 1):** `src/pyautopsy/evidence/image.py` is the *only* module importing `pytsk3` (and `pyewf` lazily, inside the E01 branch). `open_image(path)` detects format by extension (`.E01/.Ex01/.S01/.L01` → EWF, everything else → raw) and returns a plain `ImageHandle` value object exposing `read(offset,size)`/`get_size()`/`close()` plus the detected format — no pytsk3/pyewf type leaks past this module (D-06). Raw images open via `pytsk3.Img_Info` (read-only by construction, never mounts — D-05/P1); E01 opens via the verbatim canonical `EWFImgInfo(pytsk3.Img_Info)` adapter (`TSK_IMG_TYPE_EXTERNAL`, delegating `read`→`seek`+`read`, `get_size`→`get_media_size`, `close`→`close`). A missing `pyewf` raises an actionable `ImageOpenError` ("install pyautopsy[ewf] + libewf-dev"), not a stack trace (PITFALLS P5). `tsk_version()` records the libtsk version (`4.15.0`) for the COC record (A1).
- **Integrity layer (INGEST-02/03, Task 2):** `src/pyautopsy/evidence/integrity.py` is pure Python. `hash_image(handle, chunk=8MiB)` streams ONE pass over `read(offset,size)` updating both `hashlib.md5()` and `hashlib.sha256()` (D-07) — proven chunk-invariant and equal to a `hashlib` reference (including over the real `tiny_raw.dd`). `verify_acquisition(computed, supplied)` does a case-insensitive hex compare (algorithm chosen by digest length) and returns a `VerifyResult`; `VerifyResult.raise_for_status()` turns FAIL into a loud, non-zero-exit-worthy `IntegrityError` (D-08). `reverify(handle, baseline)` re-hashes at end of run and raises on any drift (INGEST-03). `assert_source_not_mounted(path)` refuses a source that is itself a mountpoint (P1, ASVS V4), with an injectable mounts table for testing. SHA-256 is the forensic primary; MD5 is documented as legacy interop only, not tamper-evidence (ASVS V6). No write/mount/losetup path to the source exists anywhere in the module.
- **Quality gates:** target suite `pytest -q tests/test_image.py tests/test_ewf_adapter.py tests/test_integrity.py tests/test_readonly_guarantee.py` → 38 passed; full `pytest -q` → 62 passed, 1 xfailed (the 01-00 ingest smoke stays xfail until 01-04); `ruff check` clean; `mypy src` clean (11 files); single-seam grep gate holds (no module other than `evidence/image.py` imports pytsk3/pyewf).

## Task Commits

1. **Task 1: Single native seam — open raw/dd + E01 read-only (INGEST-01)** — `5118e34` (feat; test + impl together)
2. **Task 2: Streaming integrity hashing + read-only guarantee + re-verify (INGEST-02/03)** — `3625662` (feat; test + impl together)

**Plan metadata:** _(final docs commit — see below)_

## Files Created/Modified
- `src/pyautopsy/evidence/__init__.py` — evidence package; re-exports the image seam + integrity API.
- `src/pyautopsy/evidence/image.py` — **the sole pytsk3/pyewf importer**: `open_image`, `detect_format`, `EWFImgInfo`, `ImageHandle`, `ImageFormat` (StrEnum), `ReadableImage` protocol, `ImageOpenError`, `tsk_version`.
- `src/pyautopsy/evidence/integrity.py` — `hash_image`, `verify_acquisition`, `reverify`, `assert_source_not_mounted`, `VerifyResult`, `IntegrityError`, `MountedSourceError`.
- `pyproject.toml` — added a `[[tool.mypy.overrides]]` block (`ignore_missing_imports` for `pytsk3`/`pyewf`, the stub-less native bindings).
- `tests/test_image.py` — raw open read-only, format-routing parametrize, missing-file error, E01-without-pyewf install hint, TSK version exposed.
- `tests/test_ewf_adapter.py` — mocked-handle delegation of `read`/`get_size`/`close`; subclass check (`pytest.importorskip("pytsk3")`).
- `tests/test_integrity.py` — hashlib-reference equality, default-chunk, empty source, real-fixture pass, chunk-invariance, acquisition PASS (md5/sha256), loud FAIL, unknown-length reject, reverify pass + mismatch.
- `tests/test_readonly_guarantee.py` — source mtime/size unchanged after open+hash; mounted-source refused; file residing on a mount allowed; default `/proc/mounts` consulted.

## Decisions Made
- **Mounted-source guard semantics (Rule 1 fix — see Deviations):** refuse only a source path that is *itself* a mountpoint, not any file under a non-root mount. This is the portable, defensible reading of P1 (the actionable case is a loop-mounted evidence filesystem) and avoids rejecting ordinary images that merely sit on `/home` or `/tmp`.
- **Algorithm selection by digest length:** the supplied acquisition hash's hex length picks the algorithm (32→md5, 64→sha256); an unrecognised length raises `IntegrityError` so an uncomparable hash can never silently "pass".
- **`tsk_version()` attribute probing:** `TSK_VERSION_STR` is present (`4.15.0`) but the function probes for any VERSION-ish attribute with an `unknown` fallback — resolving 01-RESEARCH Open Question A1 without hard-coding an attribute name.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking] mypy could not resolve the new native imports**
- **Found during:** Task 1 (mypy after writing `image.py`).
- **Issue:** `pytsk3`/`pyewf` are native C-extension bindings shipping no type stubs, so `mypy src` failed with `import-not-found` the moment the seam imported them — breaking the project's mypy-clean gate.
- **Fix:** Added a `[[tool.mypy.overrides]]` block to `pyproject.toml` setting `ignore_missing_imports = true` for `pytsk3`/`pyewf` only (scoped to the two stub-less bindings, which are confined to the single seam). No blanket suppression.
- **Files modified:** `pyproject.toml`.
- **Verification:** `mypy src` → Success (11 files).
- **Committed in:** `5118e34` (with Task 1).

**2. [Rule 1 — Bug] Mounted-source guard was over-broad ("at or under a mountpoint")**
- **Found during:** Task 2 (the default-`/proc/mounts` test failed).
- **Issue:** The first implementation refused any source *at or under* any non-root mountpoint. On this host `/tmp` is a separate tmpfs mount, so a perfectly ordinary temp evidence file under `/tmp` was wrongly refused. Refusing every file on a non-root partition (`/home`, `/tmp`, `/var`) would make the guard reject normal evidence on most hosts — a correctness bug, not a forensic gain.
- **Fix:** Tightened the guard to refuse only a source whose resolved path *is* a mountpoint (the unambiguous "this is a mounted filesystem" P1 signal). Updated `test_assert_not_mounted_refuses_path_under_mountpoint` → `test_assert_not_mounted_allows_file_residing_on_a_mount` to encode the corrected, portable behaviour; the exact-mountpoint refusal and the default-`/proc/mounts` allow case both pass.
- **Files modified:** `src/pyautopsy/evidence/integrity.py`, `tests/test_readonly_guarantee.py`.
- **Verification:** `pytest -q tests/test_readonly_guarantee.py` → 5 passed (incl. on this tmpfs host).
- **Committed in:** `3625662` (with Task 2).

---

**Total deviations:** 2 auto-fixed (1× Rule 3, 1× Rule 1). No architectural changes; no new dependencies; no scope creep.

## Threat Model Coverage
- **T-1-01 (Tampering/Repudiation, source open):** `pytsk3.Img_Info`/`EWFImgInfo` open the source byte-level read-only and never mount; `assert_source_not_mounted` refuses a mounted-source path (tested). No `mount`/`losetup`/write path anywhere.
- **T-1-02 (Repudiation/Tampering, hashing):** stdlib `hashlib` (never hand-rolled), SHA-256 primary + MD5 interop; `verify_acquisition` PASS/FAIL vs supplied hash; `reverify` end-of-run; mismatch → loud `IntegrityError` (non-zero-exit-worthy).
- **T-1-03 (Tampering, evidence modification):** no write path to the source; source mtime + size asserted unchanged across open+hash (tested).
- **T-1-02-B (Information Disclosure, native parsing):** parsing confined to the trusted TSK/libewf libraries at one seam; pinned versions; no network egress.

## Known Stubs
None. The E01/EWF *runtime* path is import-guarded (pyewf is unavailable on this host — no libewf), but the adapter logic is fully unit-proven against a mocked `pyewf.handle` (01-RESEARCH §Environment Availability / A4); the Containerfile (01-00) bakes libewf for real E01 verification. This is the planned, documented environment caveat, not a stub blocking INGEST-01.

## Verification Evidence
- `pytest -q tests/test_image.py tests/test_ewf_adapter.py tests/test_integrity.py tests/test_readonly_guarantee.py` → 38 passed.
- Full `pytest -q` → 62 passed, 1 xfailed (`test_ingest_smoke`, the 01-04 Walking Skeleton target).
- `ruff check src/pyautopsy/evidence tests/test_image.py tests/test_ewf_adapter.py tests/test_integrity.py tests/test_readonly_guarantee.py` → all checks passed.
- `mypy src` → Success, no issues found in 11 source files.
- Single-seam grep gate: `grep -rl "import pytsk3|import pyewf" src/pyautopsy --include="*.py" | grep -v evidence/image.py` → empty (PASS).
- Real-fixture cross-check: `hash_image` over the seam == `hashlib.sha256(tiny_raw.dd)` = `5eb4ca70…20ee6`.
- TSK version recorded: `TSK_VERSION_STR` = `4.15.0`.

## TDD Gate Compliance
Config `tdd_mode` is false, so separate RED/GREEN gate commits were not required. Both tasks nonetheless followed TDD: each test file was written first and confirmed to fail for the right reason (`ModuleNotFoundError: No module named 'pyautopsy.evidence.image'` / `'…integrity'`) before implementation, then passed. Test + implementation were committed together per the 01-00/01-01 convention.

## Self-Check: PASSED
All 7 created files + the modified `pyproject.toml` exist on disk; both task commits (`5118e34`, `3625662`) are present in git history.
