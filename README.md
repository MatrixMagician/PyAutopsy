<!-- generated-by: gsd-doc-writer -->
# PyAutopsy

Forensically-sound disk-image ingest and analysis on [The Sleuth Kit](https://www.sleuthkit.org/)
— a read-only Python/Linux CLI that turns a raw (`dd`) or E01/EWF disk image into a
defensible case directory: integrity hashes, a filesystem inventory (including
deleted entries), deleted-file recovery, a merged MACB + system-log super-timeline,
content/IOC search, and byte-deterministic HTML + JSON reports.

> **Status:** `0.1.0` — Development Status: 3 - Alpha. Published on
> [PyPI](https://pypi.org/project/pyautopsy/) (`pip install pyautopsy`). Requires
> Python >= 3.11 on Linux.

> **Forensic soundness is non-negotiable.** Evidence is opened read-only at the byte
> layer via The Sleuth Kit — it is **never mounted** and **never modified**. All
> output goes to a separate case directory, and the source hash is re-verified at the
> end of every run.

## Installation

The Python bindings wrap native C libraries. `pytsk3` (pinned to `pytsk3==20260520`)
ships binary wheels that bundle `libtsk`, so a **raw/dd-only** install usually needs no
system packages. The optional **E01/EWF** support (`libewf-python`, the `[ewf]` extra)
is sdist-only and **must compile against `libewf-dev`**, so it requires the native
development headers below.

**Native system dependencies (only needed for the `[ewf]` extra):**

```bash
# Fedora / RHEL
sudo dnf install -y sleuthkit sleuthkit-devel libewf libewf-devel \
    gcc gcc-c++ python3-devel

# Debian / Ubuntu / Kali
sudo apt install -y libtsk-dev libewf-dev build-essential python3-dev
```

**Python package (requires Python >= 3.11):**

```bash
# Core (raw/dd images only — light install, no system libewf required)
pip install pyautopsy

# With E01/EWF support (requires the native libewf-dev headers above)
pip install "pyautopsy[ewf]"
```

If the host lacks `libewf-dev`, the core (raw/dd) install still works; only the `[ewf]`
extra needs the native library.

**From source (development checkout — tests, linting, type checking):**

```bash
git clone https://github.com/MatrixMagician/PyAutopsy.git
cd PyAutopsy
pip install -e ".[dev]"
```

## Quick start

```bash
# One command: ingest → walk → timeline → report.
pyautopsy analyze evidence.dd \
    --case ./case --examiner "Your Name" --evidence-id E1

# Outputs land under the case directory:
#   case/reports/report.html   (human-readable, byte-deterministic)
#   case/reports/report.json   (structured/exportable, byte-deterministic)
ls ./case/reports/
```

`analyze` requires a **fresh** case directory — a pre-existing `case.db` fails loudly
so a prior case is never silently overwritten.

## Usage

PyAutopsy exposes one all-in-one command (`analyze`) plus the individual stages it
composes, so you can run the full pipeline or drive each step against an existing case.

| Command | What it does |
|---------|--------------|
| `analyze` | Full single-command pipeline: read-only ingest → filesystem walk → MACB timeline → HTML + JSON report. Recovery, known-file filtering, log parsing, and search are opt-in flags. |
| `ingest` | Open the image read-only, hash it (MD5 + SHA-256), record the chain of custody, write the audit log, and re-verify the source hash at end of run. Creates the case directory. |
| `walk` | Inventory every volume's filesystem into normalized per-file rows — including deleted entries, with allocated/unallocated status and inode/MFT addressing. |
| `recover` | Recover deleted/orphan file content into a confined `recovered/` tree with an honest intact-vs-partial confidence tier. The evidence source is never written. |
| `logs` | Parse the image's `auth.log`/`secure` (incl. rotated `.gz` members) into the shared super-timeline, time-resolved to UTC with the inferred year flagged per event. |
| `search` | Search allocated content, unallocated space, and file hashes for literal/regex terms or IOC lists, reporting hits by file and absolute byte offset. |

**Full analysis with recovery, known-file filtering, logs, and a search term:**

```bash
pyautopsy analyze evidence.E01 \
    --case ./case --examiner "Your Name" --evidence-id E1 \
    --recover \
    --nsrl /path/to/nsrl-rds.sqlite \
    --logs \
    --search "password"
```

**Drive individual stages against an existing case (created by `ingest`):**

```bash
pyautopsy ingest evidence.dd --case ./case --examiner "Your Name" --evidence-id E1
pyautopsy walk    evidence.dd --case ./case
pyautopsy recover evidence.dd --case ./case
pyautopsy search  evidence.dd --case ./case --term "secret" --regex
```

Every command opens the source read-only, records each operation in an append-only
audit log, and exits non-zero on any integrity or read-only-boundary failure *after*
recording a FAIL audit event. Run `pyautopsy --help` (or `pyautopsy <command> --help`)
for the complete option set.

### Case directory layout

A case directory is self-contained and separate from the evidence:

```
case/
├── case.db                  # SQLite case store (chain of custody, inventory, timeline)
├── logs/
│   └── audit.jsonl          # append-only audit log
├── exports/                 # exported artifacts
├── recovered/               # recovered deleted/orphan file content (recover/--recover)
└── reports/
    ├── report.html          # byte-deterministic human-readable report
    ├── report.json          # byte-deterministic structured/exportable report
    └── run_metadata.json     # volatile sidecar (timestamps, host, durations)
```

`report.html` and `report.json` are whole-file byte-deterministic across runs; all
volatile run metadata is isolated in the `run_metadata.json` sidecar so reports remain
reproducible and hashable.

## Container

A `Containerfile` is provided that bakes `sleuthkit` + `libewf` and installs the
package with the `[ewf]` extra, so both raw and E01 ingest work out of the box. It runs
as a non-root user and expects evidence mounted read-only:

```bash
podman build -t pyautopsy -f Containerfile .
# or: docker build -t pyautopsy -f Containerfile .

podman run --rm -v "$PWD:/data:ro,Z" pyautopsy \
    pyautopsy ingest /data/evidence.dd --case /data/case --examiner you --evidence-id E1
```

## Development

```bash
pip install -e ".[dev]"
pytest -q              # run the test suite (src layout via pythonpath=["src"])
ruff check src tests   # lint + import sort
mypy src               # static type checking
```

## License

PyAutopsy is released under the MIT License. See [`LICENSE`](LICENSE).
