# PyAutopsy

Forensically-sound disk-image ingest on [The Sleuth Kit](https://www.sleuthkit.org/)
— a read-only Python/Linux CLI that turns a raw (`dd`) or E01/EWF disk image
into a defensible case directory: integrity hashes, a SQLite case store, an
append-only audit log, and a hardened safe-extraction jail.

> **Forensic soundness is non-negotiable.** Evidence is opened read-only at the
> byte layer via The Sleuth Kit — it is **never mounted** and **never modified**.
> All output goes to a separate case directory.

## Status

Walking-Skeleton phase (Phase 1 — Forensic Foundation). The `pyautopsy ingest`
command is being assembled across the phase's vertical-slice plans.

## Native system dependencies

The Python bindings wrap C libraries. `pytsk3` ships binary wheels that bundle
`libtsk`, so a **raw/dd-only** install usually needs no system packages. The
optional **E01/EWF** support (`libewf-python`) is sdist-only and **must compile
against `libewf-dev`**, so it requires the native development headers below.

### Fedora / RHEL

```bash
sudo dnf install -y sleuthkit sleuthkit-devel libewf libewf-devel \
    gcc gcc-c++ python3-devel
```

### Debian / Ubuntu / Kali

```bash
sudo apt install -y libtsk-dev libewf-dev build-essential python3-dev
```

## Install

```bash
# Core (raw/dd images only — light install, no system libewf required)
pip install pyautopsy

# With E01/EWF support (requires the native libewf-dev headers above)
pip install "pyautopsy[ewf]"

# Development (tests, linting, type checking)
pip install -e ".[dev]"
```

If the host lacks `libewf-dev`, the core (raw/dd) install still works; only the
`[ewf]` extra needs the native library. Opening an E01 image without the extra
fails with a clear "install pyautopsy[ewf]" message rather than a stack trace.

## Container

A `Containerfile` is provided that bakes `sleuthkit` + `libewf` and installs the
package with the `[ewf]` extra, so both raw and E01 ingest work out of the box:

```bash
podman build -t pyautopsy -f Containerfile .
# or: docker build -t pyautopsy -f Containerfile .

podman run --rm -v "$PWD:/data:ro,Z" pyautopsy \
    pyautopsy ingest /data/evidence.dd --case /data/case --examiner you --evidence-id E1
```

## Development

```bash
pip install -e ".[dev]"
pytest -q          # run the test suite (src layout via pythonpath=["src"])
ruff check src tests
mypy src
```

## License

See [`LICENSE`](LICENSE).
