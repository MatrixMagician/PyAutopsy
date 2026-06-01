<!-- generated-by: gsd-doc-writer -->
# Contributing to PyAutopsy

PyAutopsy is a forensically-sound disk-image ingest and analysis tool built on
The Sleuth Kit (via `pytsk3`). Because its output is intended to support evidence
presentation, contributions are held to two bars at once: ordinary code quality
**and** forensic soundness. This guide covers both.

## Development setup

See [README.md](README.md) for an overview and quick start, and
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the module layout and the design
constraints (the `D-*` decision IDs referenced throughout the code and tests).

PyAutopsy targets **Python >= 3.11 on Linux** and uses a `src/` layout with
[hatchling](https://hatch.pypa.io/) as the build backend.

```bash
# Clone
git clone git@github.com:MatrixMagician/PyAutopsy.git
cd PyAutopsy

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install the package plus the dev tooling (pytest, ruff, mypy)
pip install -e ".[dev]"
```

The native forensic engine, The Sleuth Kit (`libtsk`), must be present on the
host for `pytsk3` to import. The optional `ewf` extra (`pip install -e ".[dev,ewf]"`)
adds E01/EWF image support via `libewf-python`, which is sdist-only and requires
system `libewf-dev` to build. See [docs/CONFIGURATION.md](docs/CONFIGURATION.md)
for the full system-package list.

## Code-quality gates

Every pull request must pass all three gates below. Run them locally before
opening a PR; they are configured in `pyproject.toml`.

| Gate | Command | What it enforces |
|------|---------|------------------|
| Lint + format | `ruff check src tests` | pycodestyle (E), pyflakes (F), isort (I), pyupgrade (UP), bugbear (B); line length 88. |
| Format check | `ruff format --check src tests` | Consistent formatting. |
| Static typing | `mypy` | `disallow_untyped_defs`, `warn_unused_ignores`, `warn_redundant_casts`, `no_implicit_optional` over `src/`. |
| Tests | `pytest` | Full suite; `pythonpath = ["src"]`, `testpaths = ["tests"]`. |

Notes on the configured rules:

- **`UP017` is intentionally ignored.** Ruff would rewrite `timezone.utc` to
  `datetime.UTC`, but the explicit `timezone.utc` form is the documented
  forensic-soundness idiom (D-10). Keep `timezone.utc`; do not "modernize" it.
- **mypy stub suppression is allowlisted to the seam.** `pytsk3` and `pyewf` ship
  no type stubs, so `ignore_missing_imports` is set for those two modules only.
  Do not add new modules to that override list — native bindings belong behind the
  evidence seam (see below).
- New code must be fully type-annotated; `disallow_untyped_defs` will reject
  untyped function definitions.

## Forensic-soundness constraints (mandatory)

These are not style preferences. A change that violates any of them is not
acceptable regardless of how clean the code is, because it breaks the evidentiary
guarantees PyAutopsy exists to provide. Several are enforced by executable tests.

### 1. Evidence is read-only — never mount or write the source

The source disk image must be provably never modified. All access goes through
the read-only seams (`pyautopsy.evidence.image` / `pyautopsy.evidence.filesystem`),
which read bytes through TSK/EWF file-like objects and never write to the source.
The codebase asserts this directly: `tests/test_readonly_guarantee.py` stats the
source's `st_mtime_ns` and `st_size` before and after `ingest`, `walk`, `recover`,
and `search`, and requires them unchanged.

- Never `mount` an evidence image, especially not read-write or via loopback.
  The guard `assert_source_not_mounted` (re-asserted before and after image access
  by `run_recover` / `run_search`) raises `MountedSourceError` if the source path
  is itself a mountpoint.
- All recovered/derived bytes must be written **only** under the case directory
  (`<case>/recovered/`), never back to the source.

### 2. Output must be byte-deterministic and hashable

Analytical output must be a pure function of the evidence — not of when, where, or
in what order the tool ran. `tests/test_reproducibility.py` runs `analyze` twice
into separate case directories and asserts that `report.json` and `report.html`
are **byte-identical** across runs (including the recover+filter and `--logs`
super-timeline paths).

To preserve this:

- Do not introduce iteration order, set ordering, dict insertion order, or
  enumeration order that varies run-to-run. Where ties are possible (e.g. timeline
  events at the same second), break them with content-derived, stable keys — the
  log registry's **declared parser order** and the store's `source, actor, id`
  tiebreak exist precisely for this (D-25/D-26/CR-01).
- Evidence integrity hashes (SHA-256 primary; MD5/SHA-1 for NSRL/EWF
  compatibility) are part of the analytical content and must reproduce exactly.

### 3. No wall-clock leakage into persisted analytical timestamps

Run-time wall-clock values (when the tool was executed) must stay segregated from
analytical content. Per `tests/test_reproducibility.py`, run metadata such as
`created_utc` / `acquired_utc` and the report's `generated_utc` live in
segregated columns and in a separate `run_metadata.json` sidecar — they are
**excluded** from the byte-identical comparison and are *expected to differ*
between runs.

- Never embed `datetime.now()` (or any wall-clock value) into `report.json`,
  `report.html`, or analytical database columns.
- Carry timestamps from the evidence itself; resolve log timestamps through
  `pyautopsy.log.timeresolve` with honest per-event tz/year flagging (D-46), never
  by guessing against the host clock.

### 4. Native bindings stay behind the evidence seam

All `pytsk3` / `pyewf` imports are confined to an explicit allowlist:
`evidence/image.py` (byte layer) and `evidence/filesystem.py` (FS layer). This is
enforced by `tests/test_seam_allowlist.py`, which fails if any file **outside**
the allowlist imports `pytsk3` or `pyewf` (D-06/D-14).

- Add new native-binding access only inside those two seam files. Everything else
  consumes the seam's read-only byte-reader closures and value objects.
- Do not add a second native binding. Phase-level dependency discipline (D-43) is
  guarded by `tests/test_no_new_deps.py`, which pins `[project.dependencies]` to
  its baseline and explicitly forbids `python-systemd` / journald bindings in any
  dependency table. New runtime dependencies require an explicit, deliberate
  decision and a baseline update — they are not added silently.

## Adding a log parser

Log parsing uses a minimal extension seam (EXT-01) in `pyautopsy.log.registry`. A
parser is any object satisfying the `LogParser` protocol:

- `name: str` — a stable short name (e.g. `"auth"`, `"syslog"`).
- `matches(self, path: str) -> bool` — claims the files it should handle.
- `parse(self, text, ctx) -> Iterable[ParsedRecord]` — turns decoded log text into
  `ParsedRecord` value objects.

Steps:

1. Create a new module under `src/pyautopsy/log/` (use `syslog.py` as a template).
2. Implement a parser class satisfying the protocol. Emit one `ParsedRecord` per
   line. **Never silently drop a line** — a line that matches no known pattern
   still becomes a record carrying its raw `message` (the honesty discipline:
   describe the observed line only, never inferred intent).
3. Carry the timestamp as the *raw* naive string in `raw_timestamp` (plus any
   embedded `epoch`); UTC resolution and flagging happen later in
   `pyautopsy.log.timeresolve`. Do not resolve against the host clock in the parser.
4. Register the parser singleton at import time, in declared order:

   ```python
   from pyautopsy.log.registry import ParsedRecord, register

   class MyLogParser:
       name = "mylog"
       def matches(self, path: str) -> bool: ...
       def parse(self, text, ctx=None): ...

   # Declared order is load-bearing for determinism — append at import time.
   mylog_parser = register(MyLogParser())
   ```

5. Import the module for its registration side effect in
   `src/pyautopsy/log/__init__.py` (with a `# noqa: F401` comment, matching the
   existing `auth` / `syslog` / `shell_history` imports). This guarantees
   `iter_parsers()` is fully populated on the orchestrated `run_logs` path, not
   only when a caller imports your module directly.

Because the registry is iterated in **declared (registration) order**, the order
in which you register fixes the per-line parse order and therefore the timeline
tiebreak. Choose it deliberately and add a determinism regression test. The
orchestrator (`pyautopsy.core.logs.run_logs`) does not need to change.

## Commit and PR conventions

The project history uses **Conventional Commits** with a phase/plan scope. Match
the existing style:

- Format: `type(scope): summary`, e.g.
  `feat(05-02): syslog/messages parser (LOG-02)`,
  `fix(05): bound rotated .gz inflation against decompression bombs`,
  `test(05-00): add RED stubs for logs/search`,
  `docs(05): phase verification passed`.
- Common types: `feat`, `fix`, `test`, `docs`, `chore`.
- Keep commits atomic and focused; prefer split commits over one large mixed change.
- Reference the relevant requirement/decision IDs (`LOG-02`, `D-14`, `CR-01`, …)
  in the summary or body where they apply — they tie the change to the design
  rationale the tests guard.

For a pull request:

- Branch from `main`; do not push directly to `main`.
- Ensure all four gates pass locally: `ruff check`, `ruff format --check`, `mypy`,
  `pytest`.
- Add or update tests for behaviour you change — especially a determinism /
  read-only regression test for anything touching the evidence, timeline, or
  report paths.
- Describe what changed and why, and call out any impact on the forensic-soundness
  guarantees above.

There is currently no PR or issue template and no documented branch-naming
convention in the repository; follow the conventional-commit and branch-from-`main`
guidance above.

## Reporting issues

Report bugs and feature requests via GitHub Issues at
<https://github.com/MatrixMagician/PyAutopsy/issues>. For bug reports, include:

- Steps to reproduce (exact `pyautopsy` command and flags).
- The image format and a description of the source (do **not** attach real
  evidence or sensitive data).
- Expected vs. actual behaviour, including any divergence in hashes or
  run-to-run determinism.
- Your environment: Python version, OS/distribution, and The Sleuth Kit
  (`libtsk`) version.

## License

PyAutopsy is released under the **MIT License**. By contributing, you agree that
your contributions are licensed under the same terms. See [LICENSE](LICENSE) for
the full text.
