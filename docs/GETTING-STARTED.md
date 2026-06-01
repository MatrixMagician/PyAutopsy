<!-- generated-by: gsd-doc-writer -->
# Getting Started

This walkthrough takes you from a clean machine to a finished forensic report:
install the package (and, for E01 support, the native libraries), run a single
end-to-end analysis on a disk image, and find the produced `report.html` +
`report.json`.

PyAutopsy treats evidence as read-only — the source image is opened at the byte
layer via The Sleuth Kit, **never mounted and never modified**, and its hash is
re-verified at the end of every run. All output goes to a separate case directory.

## Prerequisites

- **Python `>= 3.11`** (3.11–3.14 are declared supported in `pyproject.toml`).
- **Linux** — the project targets `POSIX :: Linux` and the forensic stack is built
  around native C libraries available there.
- **The Sleuth Kit / `libtsk`** — provides the core filesystem analysis and
  deleted-file recovery. The required `pytsk3` wheel bundles `libtsk`, so a
  **raw/dd-only** install usually needs no system package. Installing `libtsk`
  development headers (`sleuthkit-devel` / `libtsk-dev`) is only required if you
  build `pytsk3` from source.
- **`libewf` + development headers** — only needed for the optional E01/EWF
  evidence-container support (the `[ewf]` extra), which is sdist-only and must
  compile against `libewf-dev`.

Confirm your Python version before installing:

```bash
python3 --version    # must report 3.11 or newer
```

## Installation

### Quick start: install from PyPI

The fastest path is to install the published package straight from PyPI into a
virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate

# Core install — raw/dd images only (no system libewf required)
pip install pyautopsy

# Or with E01/EWF support (requires the libewf-dev headers — see below)
pip install "pyautopsy[ewf]"
```

The core install pulls the `pytsk3` wheel (which bundles `libtsk`), so raw/`dd`
analysis works with no system package. The `[ewf]` extra still needs the native
`libewf-dev` headers to build `libewf-python`; install them first (see
[Install native system dependencies for E01/EWF](#optional-install-native-system-dependencies-for-e01-ewf)).

Skip to [Verify the install](#verify-the-install) once `pip` finishes.

### Install from source

Use this path to work against the latest `main` or to develop on PyAutopsy.

#### 1. (Optional) Install native system dependencies for E01/EWF

Skip this step entirely if you only handle raw/`dd` images. The native headers
below are required only for the `[ewf]` extra (whether you install from PyPI or
from source).

```bash
# Fedora / RHEL
sudo dnf install -y sleuthkit sleuthkit-devel libewf libewf-devel \
    gcc gcc-c++ python3-devel

# Debian / Ubuntu / Kali
sudo apt install -y libtsk-dev libewf-dev build-essential python3-dev
```

These are the same packages baked into the project's `Containerfile`, so the
container image is a known-good reference environment with full raw + E01 support.

#### 2. Clone the repository

```bash
git clone https://github.com/MatrixMagician/PyAutopsy.git
cd PyAutopsy
```

#### 3. Install the Python package

Use a virtual environment to keep the forensic toolchain isolated:

```bash
python3 -m venv .venv
source .venv/bin/activate

# Core install — raw/dd images only (no system libewf required)
pip install .

# Or with E01/EWF support (requires the libewf-dev headers from step 1)
pip install ".[ewf]"
```

### Verify the install

Either path puts a `pyautopsy` command on your `PATH` (the `[project.scripts]`
entry point `pyautopsy = pyautopsy.cli.main:app`). Verify it:

```bash
pyautopsy --version    # prints: pyautopsy 0.1.0
pyautopsy --help       # lists all commands
```

## First run: one-command analysis

`analyze` runs the whole pipeline — read-only ingest → filesystem walk → MACB
timeline → HTML + JSON report — in a single process. It requires four inputs:

- a **path to the evidence image** (raw/`dd` file, or the first `.E01` segment),
- `--case` — the case directory to create (must be **fresh**, see below),
- `--examiner` — the accountable examiner's name,
- `--evidence-id` — your evidence identifier.

```bash
pyautopsy analyze evidence.dd \
    --case ./case \
    --examiner "Your Name" \
    --evidence-id E1
```

On success the command prints a summary including the report paths, for example:

```
analyze complete
  case:               case
  files inventoried:  1234
  deleted entries:    12
  files recovered:    0
  known matches:      0
  log events:         0
  search hits:        0
  timeline events:    1280
  report (json):      case/reports/report.json
  report (html):      case/reports/report.html
```

### The fresh-case requirement

`analyze` requires a case directory that does **not** already contain a `case.db`.
A pre-existing case store fails loudly so a prior case is never silently
overwritten. For a re-run, choose a new `--case` directory (or remove the old one
yourself — PyAutopsy will not do it for you).

### Locating the reports

Both reports land under `<case>/reports/`:

```bash
ls ./case/reports/
# report.html          human-readable, byte-deterministic
# report.json          structured/exportable, byte-deterministic
# run_metadata.json    volatile sidecar (timestamps, host, durations)

# Open the human-readable report in a browser
xdg-open ./case/reports/report.html
```

`report.html` and `report.json` are whole-file byte-deterministic across runs:
all volatile run details (timestamps, host, durations) are isolated in the
`run_metadata.json` sidecar so the two reports stay reproducible and hashable.
See [ARCHITECTURE.md](ARCHITECTURE.md) for the full case-directory layout.

## A fuller analysis (opt-in stages)

Recovery, known-file filtering, log parsing, and content search are **opt-in** —
without their flags the default report is byte-identical to the baseline. Enable
them on the same single command:

```bash
pyautopsy analyze evidence.E01 \
    --case ./case-full \
    --examiner "Your Name" \
    --evidence-id E1 \
    --recover \
    --nsrl /path/to/nsrl-rds.sqlite \
    --logs \
    --search "password"
```

- `--recover` — also recover deleted/orphan file content into a confined
  `recovered/` tree (the source is still never written).
- `--nsrl <db>` / `--hash-set-allow <file>` / `--hash-set-block <file>` — run
  known-file filtering against an NSRL RDS SQLite database or custom hash lists.
- `--logs` — parse the image's `auth.log`/`secure` (including rotated `.gz`
  members) into the merged super-timeline.
- `--search "<term>"` — search allocated + unallocated content and file hashes
  for a literal term, adding a search-results section to the report.
- `--timezone <IANA>` — zone used for FAT local-time handling (default `UTC`).
- `--max-hash-size <bytes>` — skip hashing files larger than this.
- `--acquisition-hash <hex>` — an MD5/SHA-256 to verify the image against on
  ingest.

Run `pyautopsy analyze --help` for the complete option set, and see
[CONFIGURATION.md](CONFIGURATION.md) for every flag, its default, and the
compile-time safety limits.

## Driving the stages individually

If you prefer step-by-step control, `analyze`'s stages are also exposed as
separate commands. Start with `ingest` (which **creates** the case directory),
then run the later stages against that **existing** case:

```bash
# 1. Create the case: open read-only, hash (MD5 + SHA-256), record chain of
#    custody, write the audit log, re-verify the source hash at end of run.
pyautopsy ingest evidence.dd --case ./case --examiner "Your Name" --evidence-id E1

# 2. Inventory every volume's filesystem, including deleted entries.
pyautopsy walk evidence.dd --case ./case

# 3. Recover deleted/orphan file content into <case>/recovered/.
pyautopsy recover evidence.dd --case ./case

# 4. Parse system logs into the merged super-timeline.
pyautopsy logs evidence.dd --case ./case

# 5. Search content + hashes (regex example).
pyautopsy search evidence.dd --case ./case --term "secret" --regex
```

Every command opens the source read-only, records each operation in an
append-only audit log (`<case>/logs/audit.jsonl`), and exits non-zero on any
integrity or read-only-boundary failure — *after* recording a `FAIL` audit event.
A clean run exits `0`; a forensic failure exits `1`; a bad invocation exits `2`.

## Running in the container

The provided `Containerfile` bakes `sleuthkit` + `libewf` and installs the
package with the `[ewf]` extra, so both raw and E01 ingest work out of the box.
It runs as a non-root `analyst` user and expects evidence mounted read-only:

```bash
podman build -t pyautopsy -f Containerfile .
# or: docker build -t pyautopsy -f Containerfile .

podman run --rm -v "$PWD:/data:ro,Z" pyautopsy \
    pyautopsy analyze /data/evidence.dd \
        --case /data/case --examiner "Your Name" --evidence-id E1
```

Mounting the evidence read-only (`:ro`) reinforces the same read-only posture the
tool enforces in software.

## Common setup issues

- **`pyautopsy: command not found`** — the entry point is only on `PATH` while
  your virtual environment is active. Re-run `source .venv/bin/activate`, or
  invoke it as `python -m pyautopsy.cli.main` is not exposed; use the installed
  `pyautopsy` script after activating the venv.
- **`pip install "pyautopsy[ewf]"` (or `".[ewf]"`) fails to build `libewf-python`**
  — the `[ewf]` extra is sdist-only and needs the native `libewf-dev` headers.
  Install the system packages from the "native system dependencies" step, or fall
  back to the core install (raw/`dd` only) if you do not need E01 support.
- **`analyze failed:` mentioning an existing `case.db`** — `analyze` (and the
  case-creating `ingest`) refuse a non-fresh case directory by design. Point
  `--case` at a new directory.
- **`analyze failed: invalid --timezone ...`** — `--timezone` must be a valid
  IANA zone name (e.g. `Europe/London`, `America/New_York`); the default is `UTC`.
- **A non-zero exit with a `FAIL` audit entry** — this is intentional. PyAutopsy
  exits non-zero (`1`) on any integrity or read-only-boundary violation rather
  than producing a report it cannot stand behind. Inspect
  `<case>/logs/audit.jsonl` for the recorded failure.

## Next steps

- [ARCHITECTURE.md](ARCHITECTURE.md) — how the pipeline, the native seam, and the
  case store fit together, plus the forensic-soundness boundaries.
- [CONFIGURATION.md](CONFIGURATION.md) — every command, argument, flag default,
  and the compile-time safety limits.
- The repository [README.md](../README.md) — quick reference for installation and
  the command table.
- Development setup: `pip install -e ".[dev]"`, then `pytest -q`,
  `ruff check src tests`, and `mypy src`.
