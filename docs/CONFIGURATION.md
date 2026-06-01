<!-- generated-by: gsd-doc-writer -->
---
title: Configuration
---

# Configuration

PyAutopsy is a single-binary forensic CLI. It has **no application environment variables**, **no
runtime configuration file**, and **no global settings**. Every run is configured entirely by:

1. **Command-line options** passed to a `pyautopsy` subcommand.
2. The **case directory** (`--case`), which is both the configuration target and the output
   destination — PyAutopsy creates and owns its layout.
3. A small set of **compile-time safety limits** baked into the source (resource caps that
   bound untrusted input). These are not user-tunable at runtime by design — they are
   forensic-safety guards, documented here for transparency.

This separation is deliberate: a forensic run must be reproducible and auditable, so behaviour
is driven by explicit invocation arguments rather than ambient state.

## Environment variables

The PyAutopsy application reads **no** environment variables for configuration. A search of
`src/pyautopsy/` for `os.environ`, `os.getenv`, and `environ[...]` returns no matches.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| _(none)_ | — | — | The tool does not consult the process environment for configuration. |

Standard Python and system variables that the underlying libraries may honour (for example the
locale or the C library's behaviour) are outside PyAutopsy's control and are not part of its
configuration surface.

### Test-fixture build variables (development only)

The **test fixture builder** (`tests/fixtures/make_fixtures.py`) *sets* a few environment
variables to make the external filesystem tools it shells out to produce byte-deterministic
images. These are **not read by PyAutopsy**, are not part of the runtime configuration surface,
and matter only to developers regenerating test fixtures. They are listed here for completeness:

| Variable | Value set | Consumed by | Why |
|----------|-----------|-------------|-----|
| `E2FSPROGS_FAKE_TIME` | `1700000000` (`_EXT4_FAKE_TIME`) | `mkfs.ext4` / `mke2fs` | Freezes ext4 superblock creation time so a rebuilt image is byte-identical. |
| `MTOOLS_SKIP_CHECK` | `1` | `mcopy` / `mdel` (mtools) | Suppresses mtools' interactive geometry check during FAT fixture builds. |

The variable name `_EXT4_FAKE_TIME` in `make_fixtures.py` is the source constant that supplies the
`E2FSPROGS_FAKE_TIME` value; there is no separate `_EXT4_FAKE_TIME` environment variable. See
[TESTING.md](TESTING.md) for fixture regeneration details.

## Config file format

PyAutopsy has **no application configuration file**. There is no `config.json`, `config.yaml`,
`.pyautopsyrc`, or equivalent, and no config loading code in the package.

The only TOML in the repository is `pyproject.toml`, which is **build and tooling metadata**, not
runtime configuration. Its tool sections (`[tool.ruff]`, `[tool.mypy]`, `[tool.pytest.ini_options]`)
configure development tools, not the CLI — see [DEVELOPMENT.md](DEVELOPMENT.md) and
[TESTING.md](TESTING.md).

## Required vs optional settings

Because configuration is per-invocation, "required" means *required arguments for a given
subcommand*. Typer validates these at parse time (type-hint-driven), and path arguments are
checked for existence and readability before any work begins.

### `ingest` and `analyze` — required arguments

The `ingest` and `analyze` commands open and hash an evidence image into a fresh case and require
chain-of-custody identity to be supplied:

| Setting | CLI flag | Required | Notes |
|---------|----------|----------|-------|
| Evidence image | _(positional)_ | **Required** | Path to a raw/dd file or the first E01 segment. Must exist, be a file, and be readable (Typer enforces `exists`, `dir_okay=False`, `readable`). |
| Case directory | `--case` | **Required** | For `ingest`: created with `case.db`, `logs/`, `exports/`. For `analyze`: **must be a fresh directory** — a pre-existing `case.db` fails loudly. |
| Examiner | `--examiner` | **Required** | Name of the accountable examiner (chain of custody). |
| Evidence id | `--evidence-id` | **Required** | Examiner-supplied evidence identifier. |

### `walk`, `recover`, `logs`, `search` — required arguments

These commands operate on an **existing** case created by a prior `ingest`:

| Setting | CLI flag | Required | Notes |
|---------|----------|----------|-------|
| Evidence image | _(positional)_ | **Required** | Same validation as above (raw/dd or first E01 segment). |
| Case directory | `--case` | **Required** | Must be an existing case directory containing `case.db`. |

A bad invocation (missing required option, non-existent/unreadable path) exits with Typer's usage
error code (`2`). A forensic integrity or read-only-boundary failure exits with code `1`, distinct
from usage errors, **after** the orchestrator records a `FAIL` audit event.

## Defaults

### Optional CLI flags and their defaults

These flags are defined on the Typer commands in `src/pyautopsy/cli/main.py`. Repeatable options
are marked; they may be passed more than once.

| Flag | Commands | Default | Effect |
|------|----------|---------|--------|
| `--acquisition-hash` | `ingest`, `analyze` | `None` (not verified) | Optional acquisition hash (MD5 or SHA-256 hex) to verify the image against on ingest. |
| `--timezone` | `walk`, `analyze` | `"UTC"` | IANA zone used for FAT local-time handling. Validated via `zoneinfo.ZoneInfo` before any work; an invalid zone exits `1`. |
| `--max-hash-size` | `walk`, `recover`, `analyze` | `None` (no limit) | Skip hashing (and, for `recover`, writing) files larger than this many bytes. |
| `--nsrl` | `recover`, `analyze` | `None` (off) | Path to an NSRL RDS SQLite DB; opts into known-file filtering (read-only). Must exist and be readable. |
| `--hash-set-allow` | `recover`, `analyze` | `None` (off) | Custom allow-sense hash list (**repeatable**); opts into known-file filtering. |
| `--hash-set-block` | `recover`, `analyze`, `search` | `None` (off) | Custom block-sense hash list (**repeatable**); known-bad hashes matched against the inventory. |
| `--recover` | `analyze` | `False` (opt-in) | Also recover deleted/orphan content. Without it, the report is byte-identical to the baseline. |
| `--logs` | `analyze` | `False` (opt-in) | Also parse the image's system logs into the super-timeline (opt-in). |
| `--search` | `analyze` | `None` (off) | Literal term searched across allocated/unallocated content and file hashes. |
| `--term` | `search` | `None` | Literal (or, with `--regex`, regex) needle (**repeatable**). |
| `--regex` | `search` | `False` | Treat each `--term` as a regular expression (ReDoS-bounded — see Safety limits). |
| `--ioc` | `search` | `None` (off) | IOC list file; indicators are searched as literal terms. |

For each command's full description and behaviour, run `pyautopsy <command> --help`.

### Discovery defaults (log parsing)

When `--logs` (or the `logs` command) runs, log discovery uses fixed default base names rather
than configurable paths. These are defined in `src/pyautopsy/log/discover.py`:

- Rotated `/var/log` sets (scan order): `auth.log`, `secure`, `syslog`, `messages`
  (`DEFAULT_LOG_BASENAMES`).
- Per-user shell-history dotfiles: `.bash_history`, `.zsh_history`, `.history`
  (`SHELL_HISTORY_BASENAMES`), discovered under `/home/<user>` and `/root`.

These lists are source constants, not user-configurable at runtime.

### Safety limits (compile-time resource caps)

PyAutopsy ingests untrusted evidence, so several hardcoded caps bound resource use and stop
decompression / regex bombs. They are constants in the source, not runtime settings — listed here
for transparency and auditability.

| Constant | Value | Where | Purpose |
|----------|-------|-------|---------|
| `_DEFAULT_MAX_TOTAL_UNCOMPRESSED` | 1 GiB | `util/safe_extract.py` | Cap on total uncompressed bytes from an archive. |
| `_DEFAULT_MAX_ENTRY_SIZE` | 256 MiB | `util/safe_extract.py` | Cap on a single extracted entry. |
| `_DEFAULT_MAX_RATIO` | 100 | `util/safe_extract.py` | Max uncompressed/compressed ratio (bomb guard). |
| `_DEFAULT_MAX_ENTRIES` | 10,000 | `util/safe_extract.py` | Max number of archive entries. |
| `_DEFAULT_MAX_DEPTH` | 3 | `util/safe_extract.py` | Max nested-archive depth. |
| `MAX_GZ_UNCOMPRESSED` | 256 MiB | `log/discover.py` | Cap on inflating a single rotated `.gz` log member. |
| `DEFAULT_CHUNK_SIZE` | 1 MiB (`1 << 20`) | `search/content.py` | Streaming read chunk size for content search. |
| `MAX_REGEX_MATCH_LEN` | 4096 | `search/content.py` | Caps regex match length (`re` has no timeout; bounds ReDoS exposure). |

## Per-environment overrides

PyAutopsy has no `development` / `staging` / `production` configuration modes — it is an operator-run
forensic CLI, not a long-lived service. There are no `.env.*` files and no `NODE_ENV`-style switch.
Each run is fully described by its command-line arguments and target case directory.

### Optional E01/EWF support (install-time variant)

The one install-time choice that changes runtime capability is the **`ewf` extra**, declared in
`pyproject.toml`:

- **Core install** (`pip install pyautopsy`) supports raw/dd images only. `libewf-python` is
  sdist-only and needs system `libewf-dev` to build, so it is kept out of the core install.
- **With E01 support** (`pip install "pyautopsy[ewf]"`) adds `libewf-python==20240506`, enabling
  ingest of EnCase/EWF (`.E01`) images via the first segment.

This is a packaging choice, not a runtime override — the same CLI flags apply either way; only the
set of openable image formats differs.

### System package prerequisites

The native forensic libraries are **system packages**, not pip dependencies, and must match the
installed Python bindings. These are environment prerequisites rather than tunable configuration:

| Library | Provides | Needed for |
|---------|----------|-----------|
| `sleuthkit` / `sleuthkit-devel` | libtsk | `pytsk3` — filesystem analysis (always required). |
| `libewf` / `libewf-devel` | libewf | `libewf-python` / `pyewf` — only for the `[ewf]` E01 extra. |

The provided `Containerfile` (Fedora 41 base) bakes both, builds the package with the `[ewf]` extra,
and runs as a non-root `analyst` user — evidence is expected to be mounted **read-only** at runtime.
On other distributions install the equivalent `-dev`/`-devel` headers before building from source.

<!-- VERIFY: Debian/Ubuntu/Kali package names (libtsk-dev, libewf-dev) are referenced in CLAUDE.md but only Fedora 41 packages are exercised by the repository's Containerfile -->

## See also

- [GETTING-STARTED.md](GETTING-STARTED.md) — prerequisites and first run.
- [DEVELOPMENT.md](DEVELOPMENT.md) — build, lint, and type-check tooling configured in `pyproject.toml`.
- Run `pyautopsy --help` or `pyautopsy <command> --help` for the authoritative, version-matched flag list.
</content>
</invoke>
