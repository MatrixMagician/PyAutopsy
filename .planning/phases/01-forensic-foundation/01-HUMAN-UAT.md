---
status: partial
phase: 01-forensic-foundation
source: [01-VERIFICATION.md]
started: 2026-05-30T17:35:00Z
updated: 2026-05-31T00:00:00Z
---

## Current Test

[testing paused — 1 item outstanding: real-E01 ingest still unconfirmed on hardware (no libewf host available)]

## Tests

### 1. Real E01 ingest on a libewf-equipped host
expected: On a host with `libewf` installed, `pip install .[ewf]` then `pyautopsy ingest sample.E01 --case /tmp/c --examiner me --evidence-id E1` creates the case store + audit log, with `image_type='ewf'` and the `EWFImgInfo` adapter delegating read/get_size/close to a live `pyewf.handle` — producing the same `case.db` + UTC audit chain as the raw/dd path.
result: skipped
reason: "User reported: skip — no libewf host available. FOLLOW-UP (2026-05-31): this host DOES have a working pyewf (libewf-python==20240506, reads OK) — original 'no host' reason superseded. New blocker is precise: the bundled libewf was compiled WITHOUT zlib (zlib-devel not installed), so E01 *write* is unsupported and no .E01 fixture can be created locally to exercise the read path. Unblock: `sudo dnf install -y zlib-devel` then `pip install --user --force-reinstall --no-binary :all: libewf-python==20240506`, then a tiny ext4 raw image (dd+mke2fs+debugfs) → sample.E01 via pyewf write → `pyautopsy ingest`. pytsk3, gcc, python3-devel, libewf-devel all already present."
why_human: This CI/dev host has no libewf/pyewf (`import pyewf` → ImportError; pytsk3 is present). The E01 adapter is real code exercised against a mocked `pyewf.handle` in CI; per 01-VALIDATION.md this is the single documented Manual-Only verification — an accepted arrangement, not a stub. Native-library confirmation needs real libs/hardware.

## Summary

total: 1
passed: 0
issues: 0
pending: 0
skipped: 1
blocked: 0

## Gaps
