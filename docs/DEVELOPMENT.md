<!-- generated-by: gsd-doc-writer -->
# Development

This guide covers local development of PyAutopsy: setting up an editable
environment, running the quality gates, the code conventions the project
enforces, building and publishing a release, and how to extend the tool with a
new log parser. It complements the contributor-facing process in
[CONTRIBUTING.md](../CONTRIBUTING.md) and the module-level design in
[docs/ARCHITECTURE.md](ARCHITECTURE.md).

## Local setup

PyAutopsy targets **Python >= 3.11 on Linux**, uses a `src/` layout, and builds
with the [hatchling](https://hatch.pypa.io/) backend (`[build-system]` in
`pyproject.toml`). Develop against an editable install with the dev tooling
group.

```bash
# Clone and enter the repo (default branch is `main`)
git clone git@github.com:MatrixMagician/PyAutopsy.git
cd PyAutopsy

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Editable install with the dev tooling group (pytest, ruff, mypy)
pip install -e ".[dev]"
```

The editable install (`-e`) means source edits under `src/pyautopsy/` take effect
without reinstalling, and `pythonpath = ["src"]` in the pytest config ensures the
tests import the in-tree package (not a stray site-packages copy) — the standard
src-layout safeguard against "tested the wrong copy" bugs.

### Native dependencies

The core engine, The Sleuth Kit (`libtsk`), must be present on the host for
`pytsk3` (`pytsk3==20260520`) to import. The `[ewf]` extra adds E01/EWF image
support via `libewf-python==20240506`, which is **sdist-only** and requires system
`libewf-dev` (plus a C toolchain) to build — that is why it is kept out of the core
install. Install it alongside dev tooling only when you need to work on the EWF
path:

```bash
# Add E01/EWF support (requires system libewf-dev to build libewf-python)
pip install -e ".[dev,ewf]"
```

See [docs/CONFIGURATION.md](CONFIGURATION.md) and
[docs/GETTING-STARTED.md](GETTING-STARTED.md) for the full system-package list and
first-run instructions.

## Build and quality-gate commands

PyAutopsy has no `package.json` scripts; the toolchain is the Python dev triad
configured entirely in `pyproject.toml`. Every change must pass all of the
following locally before opening a pull request.

| Command | Purpose |
|---------|---------|
| `ruff check src tests` | Lint. Rules: pycodestyle (`E`), pyflakes (`F`), isort (`I`), pyupgrade (`UP`), bugbear (`B`); line length 88; target `py311`. `UP017` is intentionally ignored. |
| `ruff format src tests` | Auto-format. Use `ruff format --check src tests` in pre-PR checks to verify without rewriting. |
| `mypy` | Static typing over `src/` (configured `files = ["src"]`). Strict-leaning: `disallow_untyped_defs`, `warn_unused_ignores`, `warn_redundant_casts`, `no_implicit_optional`. |
| `pytest` | Full test suite. `pythonpath = ["src"]`, `testpaths = ["tests"]`, `addopts = "-ra"`. |

## Building and publishing a release

PyAutopsy publishes to PyPI as [`pyautopsy`](https://pypi.org/project/pyautopsy/)
(version `0.1.0` is live). Distribution uses the hatchling backend; the wheel
packages `src/pyautopsy` (`[tool.hatch.build.targets.wheel]`) and the version is
read dynamically from `src/pyautopsy/__init__.py` (`[tool.hatch.version]`).

The sdist is deliberately constrained to source-only via
`[tool.hatch.build.targets.sdist]`, which sets `include = ["src/pyautopsy",
"README.md", "LICENSE"]`. Without this allowlist, hatchling's default sdist
sweeps the whole VCS tree and would leak the multi-MB test-fixture disk images
(`tests/fixtures/*.img`) and the internal `.planning/` artifacts onto PyPI. Keep
this allowlist in place; if you add a new top-level file that must ship in the
sdist, add it here explicitly.

### Cutting a release

1. **Bump the version.** Edit `__version__` in `src/pyautopsy/__init__.py` — this
   is the single source of truth that hatchling reads at build time. There is no
   separate version string in `pyproject.toml`.

2. **Build fresh artifacts.** Remove any stale `dist/` first so a re-run never
   re-uploads an old artifact, then build sdist + wheel:

   ```bash
   rm -rf dist/
   python -m build        # or: uv build
   ```

   Both invoke the hatchling backend; `uv build` does not require the `build`
   package in the active environment, whereas `python -m build` does
   (`pip install build`).

3. **Validate the artifacts.** Run `twine check` over the built distributions to
   catch metadata/README rendering problems before upload:

   ```bash
   twine check dist/*
   ```

   Optionally inspect the sdist to confirm the allowlist held — only `src/`,
   `README.md`, `LICENSE`, `pyproject.toml`, and packaging metadata should be
   present, with no `tests/`, `*.img`, or `.planning/` entries:

   ```bash
   tar tzf dist/pyautopsy-*.tar.gz
   ```

4. **Publish.** Upload to PyPI with either `uv publish` or `twine upload`:

   ```bash
   uv publish              # or: twine upload dist/*
   ```

   <!-- VERIFY: PyPI publishing credentials / token source (env var, ~/.pypirc, or CI secret) -->

There is no `.github/` CI workflow in this repository, so releases are cut
manually from a clean checkout following the steps above.

## Code conventions

### src layout

All importable code lives under `src/pyautopsy/`, split into submodules:
`audit`, `case`, `cli`, `core`, `evidence`, `filter`, `log`, `report`, `search`,
`timeline`, and `util`. New code belongs in the matching submodule; the
`[tool.ruff.lint.isort]` config sets `known-first-party = ["pyautopsy", "tests"]`
so in-repo imports group together.

### Full type annotations

`mypy` runs with `disallow_untyped_defs`, so every function and method must be
fully annotated — an untyped `def` will fail the gate. Because
`warn_unused_ignores` is on, stale `# type: ignore` comments are also flagged.
Native bindings (`pytsk3`, `pyewf`) ship no stubs, so `ignore_missing_imports` is
set **for those two modules only** via a targeted `[[tool.mypy.overrides]]`. Do
not extend that override to other modules — native bindings must stay behind the
evidence seam (below).

### Explicit UTC / forensic timestamp idiom

`UP017` is deliberately ignored in the ruff config. Ruff would rewrite
`timezone.utc` to `datetime.UTC`, but the explicit `timezone.utc` form is the
documented forensic-soundness idiom (decision **D-10**) that every later module
follows. **Keep `timezone.utc`; do not "modernize" it.** Carry analytical
timestamps from the evidence itself and resolve log timestamps through
`pyautopsy.log.timeresolve` — never embed host wall-clock time
(`datetime.now()`) into analytical output.

### Native bindings stay behind the evidence seam

All `pytsk3` / `pyewf` imports are confined to an allowlist of exactly two files —
`evidence/image.py` (byte layer) and `evidence/filesystem.py` (FS layer) — per
decisions **D-06 / D-14**. This is enforced by `tests/test_seam_allowlist.py`,
which fails if any source file outside the allowlist imports either binding (and
also asserts `evidence/image.py` is still a native importer, so the regex can't
pass vacuously). Add native-binding access only inside those two seam files;
everything else consumes the seam's read-only byte-reader closures and value
objects.

### No silent dependency creep

`tests/test_no_new_deps.py` pins `[project.dependencies]` to its baseline set
(`pytsk3`, `python-magic`, `typer`, `jinja2`) and forbids
`python-systemd` / journald bindings in any dependency table (decision **D-43**).
New runtime dependencies require a deliberate decision and an explicit baseline
update — they are not added silently.

## Extending PyAutopsy: adding a log parser

Log parsing uses a minimal extension seam (**EXT-01**) in
`pyautopsy.log.registry`. A parser is any object satisfying the `LogParser`
protocol:

- `name: str` — a stable short name (e.g. `"auth"`, `"syslog"`).
- `matches(self, path: str) -> bool` — claims the files it should handle.
- `parse(self, text, ctx) -> Iterable[ParsedRecord]` — turns decoded log text into
  `ParsedRecord` value objects.

New parsers register themselves with the registry and the orchestrator
(`pyautopsy.core.logs.run_logs`) picks them up via `iter_parsers()` — no
orchestrator change is needed.

### Steps

1. Create a new module under `src/pyautopsy/log/`. Use `syslog.py` as a template.
2. Implement a parser class satisfying the protocol. Emit one `ParsedRecord` per
   line and **never silently drop a line** — a line that matches no known pattern
   still becomes a record carrying its raw `message` (the honesty discipline:
   describe the observed line, never inferred intent). Set `action=None` /
   `outcome=None` for unmatched lines.
3. Carry the timestamp as the *raw* naive string in `raw_timestamp` (plus any
   embedded `epoch` for shell history). UTC resolution and per-event tz/year
   flagging happen later in `pyautopsy.log.timeresolve` (**D-46**) — do not resolve
   against the host clock in the parser.
4. Register the parser singleton at import time, appending in declared order
   (this mirrors `SyslogParser` in `syslog.py`):

   ```python
   from pyautopsy.log.registry import ParsedRecord, register

   class MyLogParser:
       name = "mylog"

       def matches(self, path: str) -> bool:
           leaf = path.rsplit("/", 1)[-1]
           return leaf.startswith("mylog")

       def parse(self, text, ctx=None):
           ...  # yield ParsedRecord(...) per line

   # Declared order is load-bearing for determinism — register at import time.
   mylog_parser = register(MyLogParser())
   ```

5. Import the module for its registration side effect in
   `src/pyautopsy/log/__init__.py`, with a `# noqa: F401` comment, matching the
   existing `auth` / `syslog` / `shell_history` side-effect imports. Without this,
   `iter_parsers()` is only populated when a caller imports your module directly —
   the package import on the orchestrated `run_logs` path would miss it (this was
   the **CR-01** regression).

### Why declared order matters

`iter_parsers()` yields parsers in declared (registration) order. That order fixes
the per-line parse order, which — combined with `discover`'s oldest→newest file
order — fixes the `insert_timeline_events` order and therefore the store's
surrogate-id tiebreak. This is the **CR-01** deterministic-tied-order guarantee
that keeps `report.json` / `report.html` byte-identical run-to-run. Choose your
registration position deliberately and add a determinism regression test for the
new parser.

## Branch conventions

The default branch is **`main`**. Branch from `main` and open a pull request — do
not push directly to `main`. The repository defines no `.github/` directory, so
there is **no PR template, no issue template, and no CI workflow**; the gates are
run locally. There is no documented branch-naming convention; follow the
conventional-commit and branch-from-`main` guidance in
[CONTRIBUTING.md](../CONTRIBUTING.md).

Commit messages use **Conventional Commits** with a phase/plan scope, e.g.
`feat(05-02): syslog/messages parser (LOG-02)` or
`fix(05): bound rotated .gz inflation`. Common types: `feat`, `fix`, `test`,
`docs`, `chore`. Keep commits atomic, and reference the relevant
requirement/decision IDs (`LOG-02`, `D-14`, `CR-01`, …) where they apply.

## PR process

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the full contribution and
pull-request process. In summary:

- Branch from `main`; never push directly to `main`.
- Ensure all gates pass locally: `ruff check`, `ruff format --check`, `mypy`,
  `pytest`.
- Add or update tests for any behaviour you change — especially a determinism /
  read-only regression test for anything touching the evidence, timeline, or
  report paths.
- Describe what changed and why, and call out any impact on the
  forensic-soundness guarantees (read-only evidence, byte-deterministic output,
  no wall-clock leakage, single native seam).
