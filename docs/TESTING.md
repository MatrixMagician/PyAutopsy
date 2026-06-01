<!-- generated-by: gsd-doc-writer -->
# Testing

## Test framework and setup

PyAutopsy uses **[pytest](https://docs.pytest.org/)** as its only test framework.
It is declared in the `dev` optional-dependency group in `pyproject.toml`:

```toml
[project.optional-dependencies]
dev = ["pytest", "ruff", "mypy"]
```

No version is pinned — the suite tracks the current pytest release (developed
against pytest 9.x on CPython 3.14; the project supports Python `>=3.11`).

Install the project together with its dev dependencies before running tests:

```bash
pip install -e ".[dev]"
```

The pytest configuration lives in `pyproject.toml` under
`[tool.pytest.ini_options]`:

```toml
[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
addopts = "-ra"
```

- `pythonpath = ["src"]` puts the **src-layout** package root on `sys.path`, so
  tests import the installed-style `pyautopsy` package without an editable
  install path hack (it prevents the classic "tested the wrong copy" bug).
- `testpaths = ["tests"]` scopes collection to the `tests/` directory.
- `addopts = "-ra"` prints a short summary of all non-passing (and xfail/xpass)
  results after the run.

**Most of the suite needs no native forensic toolchain.** The deterministic
ext4 / NTFS / raw / NSRL / log-search fixtures are pre-built and **committed**
under `tests/fixtures/`, so those tests run with no `mkfs`, `debugfs`, or
`mkntfs` at test time. The two FAT images, however, are **generated at test time**
(see [Running tests](#running-tests) and [Fixture and golden-image
generation](#fixture-and-golden-image-generation)): the tests that depend on
them need `mkfs.fat`, `mcopy`, `mdel` (and, for the partitioned image, `sfdisk`
and `mkfs.ext4`) on `PATH`, and **skip gracefully** when those host tools are
absent. The only hard runtime binding for the rest of the suite is `pytsk3` (a
core dependency, bundled with `libtsk`); the optional `pyewf` (`[ewf]` extra) is
mocked in `tests/test_ewf_adapter.py` rather than required.

## Running tests

Run the full suite from the project root:

```bash
pytest
```

Run a single test file:

```bash
pytest tests/test_safe_extract.py
```

Run a single test by node ID:

```bash
pytest tests/test_image.py::test_open_raw_readonly
```

Run all tests whose name matches a keyword expression (`-k`):

```bash
pytest -k "readonly or reproducib"
```

Run a single test (for example the filesystem-type detection test, which
exercises ext4, NTFS and FAT in one function):

```bash
pytest "tests/test_filesystem.py::test_fs_type_detection"
```

There is no separate `unit`/`integration`/`e2e` split and no watch-mode script
configured — the entire suite is invoked through plain `pytest`.

**FAT-fixture skips.** The FAT32 and partitioned-disk tests build their images
on the fly (the images are not committed — see below). On a host without the
`mkfs.fat` / `mtools` / `sfdisk` toolchain those tests report as **skipped**
(with an actionable message naming the missing tools) rather than failing, so a
minimal CI environment still gets a green run for everything else. Install the
host tools (on Fedora: `dosfstools` / `mtools` / `util-linux` / `e2fsprogs`) to
exercise them.

## Writing new tests

### File and function naming

Tests live directly under `tests/` (a flat layout — there are no nested test
packages). Conventions, all enforced by pytest's default collection:

- Test files are named `test_*.py` (e.g. `tests/test_walk.py`,
  `tests/test_safe_extract.py`).
- Test functions are named `test_*` with type-hinted signatures and a one-line
  (or paragraph) docstring stating the requirement and the decision/pitfall ID it
  guards (e.g. `D-14`, `RECOV-02`, `CR-01`, `Pitfall 3`).
- Module-private test helpers are prefixed with a single underscore
  (`_ingest_then_walk`, `_read_audit`, `_analyzed_store`) so they are not
  collected as tests.

### Shared fixtures (`tests/conftest.py`)

`tests/conftest.py` exposes the shared pytest fixtures. The most commonly used:

| Fixture | Provides |
|---------|----------|
| `case_dir` | A fresh, empty case-directory path under `tmp_path` (the tool creates `case.db` / `logs/` / `exports/`; the fixture only hands you the isolated root). |
| `tiny_raw_image` | Path to the committed deterministic 64 KiB raw image (`tiny_raw.dd`). |
| `tiny_ext4_image` / `tiny_ntfs_image` | Committed tiny filesystem images for the walk (known file + uid/gid/mode; ext4 also carries a deleted entry). |
| `tiny_fat32_image` / `tiny_partitioned_image` | **Generated at test time** (session-scoped), NOT committed — built once per session into a session `tmp` dir via `make_fixtures.build_tiny_fat32_image` / `build_partitioned_image`. Each `skip`s its dependent tests when the host `mkfs`/`mtools`/`sfdisk` tools are missing (the `_build_or_skip` helper). |
| `ext4_orphan_image` / `ext4_overwritten_image` / `ntfs_resident_deleted_image` | Committed recovery fixtures (orphan / overwritten / resident-deleted). |
| `nsrl_minimal_db` / `nsrl_metadata_db` | Committed NSRL-format SQLite hash-set fixtures (`FILE` and `METADATA` table variants). |
| `log_search_image` | Committed Phase-5 ext4 image carrying the whole log/search corpus (rotated `auth.log` set, `syslog`, shell history, planted needles, timezone symlink). |
| `log_search_groundtruth` | The committed ground-truth constants for `log_search_image`, loaded from `log_search_groundtruth.json`. |
| `zip_slip_tar` / `symlink_escape_tar` / `device_file_tar` / `ratio_bomb_zip` / `count_bomb_tar` | Malicious archives built lazily into `tmp_path` for the safe-extract jail tests (live bombs are never committed to disk). |

When you need a new committed evidence fixture, add a deterministic builder to
`tests/fixtures/make_fixtures.py` and expose its path through a `conftest.py`
fixture; do not generate disk images inside individual tests. The exception is a
fixture that is large *and* not byte-deterministic (like the FAT images): give
it a session-scoped builder fixture that goes through `_build_or_skip`, so the
image stays out of the repo and absent host tools `skip` rather than fail.

### Fakes for the native seam

`tests/fixtures/fake_fs.py` provides in-memory, pytsk3-shaped fakes
(`FakeFS`, `FakeDirEntry`, `DeepFakeFS`) that duck-type the `pytsk3.FS_Info`
surface `evidence/filesystem.walk_fs` consumes. These let recursion behaviours
(parent-address threading, the depth cap) be exercised without a crafted on-disk
image. The fakes read the native flag/type integers from the installed `pytsk3`
so they stay in lock-step with the seam's own constants.

## Fixture and golden-image generation

Everything is driven by `tests/fixtures/make_fixtures.py`. The
byte-deterministic golden images are **built once on a host that has the
formatting tools, then committed** to `tests/fixtures/` so CI never runs a
privileged `mkfs`. Two FAT images are the exception — they are **generated at
test time and gitignored** (see below). Re-run the module as a script to
regenerate every committed *and* generated asset side-by-side:

```bash
python tests/fixtures/make_fixtures.py
```

Regeneration needs the host formatting toolchain (on Fedora:
`e2fsprogs` / `dosfstools` / `mtools` / `ntfs-3g` / `util-linux`).

### Committed fixtures

| Fixture file | How it is built | Ground truth it carries |
|--------------|-----------------|-------------------------|
| `tiny_raw.dd` | 64 KiB of bytes from a fixed-seed LCG (`tiny_raw_bytes`) — no external tool | Byte-deterministic raw image for read-only open + streaming-hash. |
| `tiny_ext4.img` | `mkfs.ext4` + `debugfs` | One known file (uid/gid/mode `1000`/`1000`/`0644`) plus a deleted root entry (`deleted.txt`, inode 13). |
| `tiny_ntfs.img` | `mkntfs` (+ `ntfscp` if present) | NTFS system files / one known file with UTC times. |
| `ext4_orphan.img` | `debugfs` (file + parent dir removed) | An orphan file inode (`EXT4_ORPHAN_META_ADDR = 13`) with recoverable content (RECOV-02). |
| `ext4_overwritten.img` | `debugfs` (write → rm → reclaim) | A deleted victim whose blocks are reclaimed by an allocated file (RECOV-03 / D-31). |
| `ntfs_resident_deleted.img` | `mkntfs` + `ntfscp`, then an in-place MFT byte edit | A resident-`$DATA` deleted file at MFT addr 64, recovered from the MFT record (RECOV-01, Pitfall 3). |
| `nsrl_minimal.db` / `nsrl_metadata.db` | stdlib `sqlite3` (no external tool) | NSRL `FILE` / `METADATA` table variants with UPPERCASE hashes (FILTER-01, Pitfall 4). |
| `log_search_ext4.img` (+ `log_search_groundtruth.json`) | `mkfs.ext4` + `debugfs` | The whole Phase-5 corpus: rotated `auth.log`/`.1`/`.2.gz` spanning a Dec→Jan year boundary (years 2023 / 2022, anchored to the frozen debugfs clock), `syslog`, bash/zsh history, `/etc/localtime` symlink + `/etc/timezone`, allocated + unallocated search needles, an IOC term, a known-bad-hash file, and two tied-second syslog lines. |

### Generated-at-test-time fixtures (not committed, gitignored)

The two FAT images are **not** committed: they are large (64–74 MiB) and not
byte-deterministic (`mkfs.fat` stamps a wall-clock volume id), so committing them
would bloat the repo with non-reproducible binaries. Instead the session-scoped
`tiny_fat32_image` / `tiny_partitioned_image` fixtures build them on demand into
a session `tmp` dir, and `tests/fixtures/.gitignore` excludes the filenames.
Tests that need them **skip** (rather than fail) when the host tools are absent.

| Fixture file | How it is built | Required host tools | Ground truth it carries |
|--------------|-----------------|---------------------|-------------------------|
| `tiny_fat32.img` | `mkfs.fat -F 32` + `mcopy`/`mdel` (mtools) | `mkfs.fat`, `mcopy`, `mdel` | One live file + a root-level FAT deletion; FAT local-time provenance (D-16). |
| `tiny_partitioned.img` | `sfdisk` + `mkfs.fat` + `mkfs.ext4` + `mcopy` | `sfdisk`, `mkfs.fat`, `mkfs.ext4`, `mcopy` | A DOS partition table (FAT + ext4) for the volume-offset path (D-15). |

### Byte-determinism of fixtures

The ext4 and NSRL fixtures are **byte-reproducible**: `mkfs.ext4` is run with a
pinned filesystem UUID (`_EXT4_FIXED_UUID`), a pinned directory-hash seed, and a
frozen creation time via `E2FSPROGS_FAKE_TIME`; `debugfs` writes run under the
same frozen clock; and the NSRL SQLite DBs are built with a fixed `page_size`,
fixed row order, and a final `VACUUM` for a canonical layout. The NTFS fixture
reproduces its *structure and recorded ground truth* but is **not** byte-identical
(`mkntfs` offers no fixed-UUID/fixed-time option) — a documented determinism
caveat in the builder. The FAT images share that non-determinism (`mkfs.fat`
stamps a wall-clock volume id), which is the reason they are generated at test
time instead of committed. The gzip member inside the log/search image is written
with `mtime=0` so its bytes are reproducible.

Malicious-archive builders (`build_zip_slip_tar`, `build_symlink_escape_tar`,
`build_device_file_tar`, `build_ratio_bomb_zip`, `build_count_bomb_tar`) generate
their payloads programmatically at test time and are size-capped so the builders
themselves can never become resource-exhaustion bombs.

## Test conventions and guards

The suite encodes several project-specific, executable invariants that double as
architecture guards. New tests should preserve these conventions:

- **Read-only evidence (`tests/test_readonly_guarantee.py`).** Every analysis path
  is asserted to leave the source image untouched: tests `stat()` the image
  before and after open/hash, walk, recover, and search, then assert
  `st_mtime_ns` and `st_size` are unchanged. `assert_source_not_mounted` is
  exercised against a synthetic, injected `/proc/mounts` table so the host's real
  mounts are never read.

- **Native-seam allowlist (`tests/test_seam_allowlist.py`).** An executable D-14
  gate scans every `src/pyautopsy/**/*.py` file and fails if `pytsk3` or `pyewf`
  is imported anywhere outside the allowlist (`evidence/image.py`,
  `evidence/filesystem.py`). This keeps all native-binding access behind the
  single seam.

- **Byte-determinism / reproducibility (`tests/test_reproducibility.py`).** Two
  runs over the same image must produce identical analytical content and a
  byte-identical report (`test_two_analyze_runs_byte_identical_report`,
  `test_recover_filter_reproducible`), with run-specific metadata segregated from
  analytical fields. Tied timeline events (identical second, NULL filesystem meta)
  are asserted to order byte-stably across runs (`test_tied_log_events_stable`,
  `CR-01` / Pitfall 3).

- **UTC everywhere (`tests/test_timeutil.py`, `tests/test_walk.py`).** Timestamps
  are asserted to be timezone-aware UTC with an explicit `+00:00` offset; naive
  datetimes are rejected, and FAT local times are flagged as reinterpreted (D-16).

- **No new runtime dependencies (`tests/test_no_new_deps.py`).** A D-43 regression
  gate parses `pyproject.toml` and asserts no new runtime dependency (and no
  native log binding such as `python-systemd`) was added.

- **End-to-end orchestrated paths.** Several tests drive the real orchestrators
  rather than hand-importing modules — notably
  `test_run_logs_orchestrated_emits_syslog_and_shell_history` in
  `tests/test_logs.py`, which runs `run_ingest` → `run_walk` → `run_logs` over
  `log_search_image` and asserts the merged super-timeline contains auth, syslog,
  and shell-history events in one UTC total order (the `CR-01` regression that a
  hand-import had masked). CLI surfaces are smoke-tested end-to-end in
  `tests/test_cli_smoke.py` (`ingest`, `walk`, `search`, `--version`, help text).

## Test suite map

| Test file | Focus |
|-----------|-------|
| `tests/test_image.py` | Read-only image open seam, format detection, E01-without-pyewf error (INGEST-01). |
| `tests/test_ewf_adapter.py` | `EWFImgInfo` adapter over a mocked pyewf handle (INGEST-01, E01 path). |
| `tests/test_integrity.py` | Single-pass MD5/SHA-1/SHA-256 hashing, acquisition compare, short-read/mount guards (INGEST-02). |
| `tests/test_readonly_guarantee.py` | Source-never-modified + mounted-source refusal across all paths (INGEST-03). |
| `tests/test_safe_extract.py` | The `safe_extract` archive jail: zip-slip, symlink/absolute/device escapes, ratio/size/count bombs (INGEST-04, D-11). |
| `tests/test_seam_allowlist.py` | D-14 native-binding allowlist gate. |
| `tests/test_case_store.py` | SQLite case store: schema, WAL/foreign-keys, round-trips, total-order timeline reads, transactions (REPORT-01). |
| `tests/test_store_latest_source.py` | CaseStore boundary reads used by orchestrators (WR-02/WR-06). |
| `tests/test_audit_log.py` | Append-only JSONL audit log: UTC timestamps, sorted keys, never-truncate (REPORT-02). |
| `tests/test_timeutil.py` | UTC-everywhere timestamp helpers (D-10). |
| `tests/test_filesystem.py` | FS-layer seam: volume enumeration, recursion, deleted/orphan classification, depth cap. |
| `tests/test_walk.py` | Walk orchestrator: deleted inventory, MACB→UTC, FAT flagging, ownership/mode, three-digest single pass, error auditing (META-01..05). |
| `tests/test_recover.py` | Deleted-file recovery: ext4 content, NTFS resident, orphan-vs-recovered, confidence tiers (RECOV-01/02/03). |
| `tests/test_knownfiles.py` | NSRL membership + custom hash sets + variant-table discovery (FILTER-01). |
| `tests/test_logs.py` | RFC3164 parsing, auth/syslog taxonomy, shell-history, rotation reassembly, year inference, orchestrated `run_logs`. |
| `tests/test_search.py` | Streaming content/unallocated search, boundary-spanning matches, IOC + hash hits (SEARCH-01/02). |
| `tests/test_timeline.py` | Filesystem MACB timeline producer + total order (TIME-01). |
| `tests/test_supertimeline.py` | Super-timeline merge / tied-order (TIME-02, CR-01). |
| `tests/test_report.py` | Deterministic JSON + HTML reporter, autoescape, truncation note, integrity states (REPORT-03/04). |
| `tests/test_reproducibility.py` | Byte-identical reports + stable tied-event ordering across runs (CLI-02 / D-08). |
| `tests/test_ingest.py` | Ingest orchestrator: case/evidence persistence, audit trail, rollback, acquisition-hash gating. |
| `tests/test_analyze.py` | Single-command `analyze` pipeline composition (CLI-01). |
| `tests/test_cli_smoke.py` | End-to-end CLI surface: `ingest`/`walk`/`search`, help, `--version` (D-12). |
| `tests/test_no_new_deps.py` | Dependency-freeze regression gate (D-43). |

## Coverage requirements

No coverage tool (`pytest-cov`, `coverage`, `c8`) is configured in
`pyproject.toml`, and there is no coverage threshold. Coverage is instead asserted
*behaviourally*: the filesystem-walk and recovery tests verify exact file counts
and exact bytes/inode addresses against the fixtures' recorded ground truth (the
"every file" / Nyquist signal), rather than enforcing a line-coverage percentage.

## CI integration

No CI workflow is committed to this repository (there is no `.github/workflows/`
directory). The intended pre-merge gate is the local quality stack declared in
`pyproject.toml`: `ruff` (lint + format), `mypy` (static typing over `src`), and
`pytest`. The reference execution environment for full **E01/EWF** support is the
`Containerfile` (Fedora-based, bakes `sleuthkit` + `libewf` and their `-dev`
headers and installs `pyautopsy[ewf]`), since the core wheels cover the
raw/`dd`-only path without system packages. A CI image that also bundles
`dosfstools` / `mtools` / `util-linux` will run the FAT tests too; one that omits
them will simply `skip` those tests.

<!-- VERIFY: no CI/CD pipeline is committed; if a CI workflow is added later, document its trigger and test command here -->

## Next steps

- See `docs/CONFIGURATION.md` for environment and runtime configuration.
- See `docs/ARCHITECTURE.md` for the layered pipeline, the native seam, and the
  sole-writer `CaseStore` boundary these tests guard.
