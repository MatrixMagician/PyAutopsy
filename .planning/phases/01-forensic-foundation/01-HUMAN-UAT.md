---
status: partial
phase: 01-forensic-foundation
source: [01-VERIFICATION.md]
started: 2026-05-30T17:35:00Z
updated: 2026-05-30T17:35:00Z
---

## Current Test

[awaiting human testing on a libewf-equipped host]

## Tests

### 1. Real E01 ingest on a libewf-equipped host
expected: On a host with `libewf` installed, `pip install .[ewf]` then `pyautopsy ingest sample.E01 --case /tmp/c --examiner me --evidence-id E1` creates the case store + audit log, with `image_type='ewf'` and the `EWFImgInfo` adapter delegating read/get_size/close to a live `pyewf.handle` — producing the same `case.db` + UTC audit chain as the raw/dd path.
result: [pending]
why_human: This CI/dev host has no libewf/pyewf (`import pyewf` → ImportError; pytsk3 is present). The E01 adapter is real code exercised against a mocked `pyewf.handle` in CI; per 01-VALIDATION.md this is the single documented Manual-Only verification — an accepted arrangement, not a stub. Native-library confirmation needs real libs/hardware.

## Summary

total: 1
passed: 0
issues: 0
pending: 1
skipped: 0
blocked: 0

## Gaps
