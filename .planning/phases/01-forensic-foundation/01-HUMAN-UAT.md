---
status: complete
phase: 01-forensic-foundation
source: [01-VERIFICATION.md]
started: 2026-05-30T17:35:00Z
updated: 2026-05-31T15:56:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Real E01 ingest on a libewf-equipped host
expected: On a host with `libewf` installed, `pip install .[ewf]` then `pyautopsy ingest sample.E01 --case /tmp/c --examiner me --evidence-id E1` creates the case store + audit log, with `image_type='ewf'` and the `EWFImgInfo` adapter delegating read/get_size/close to a live `pyewf.handle` — producing the same `case.db` + UTC audit chain as the raw/dd path.
result: pass
verified: "2026-05-31 — PASS on a real libewf-equipped host. Verification evidence:
  - Fixture: dd 8 MiB → mke2fs ext4 → debugfs wrote f1.txt/f2.txt → ewfacquire -c none (uncompressed) → sample.E01.
  - `pyautopsy ingest sample.E01 --case /tmp/c --examiner me --evidence-id E1` → exit 0, `image type: ewf`.
  - EWFImgInfo adapter delegated to a LIVE pyewf.handle: open/hash/reverify read all 8388608 media bytes via EWF (not mocked).
  - case.db created with full schema; evidence_sources row records image_type='ewf', byte_size=8388608, tsk_version=4.15.0.
  - UTC audit chain in logs/audit.jsonl: ingest.start→write_guard(PASS)→case_init→write_guard_recheck(PASS)→open(image_type=ewf,read_only=true)→hash→reverify(PASS)→end(SUCCESS); every ts ends in +00:00.
  - SAME-AS-RAW proof: ingesting the identical media via the raw/dd path produced byte-identical sha256 (8d2623bd…291ea) and md5 (4d73b791…); only image_type differs (ewf vs raw). pyautopsy's media md5 also matched ewfacquire's own data MD5.
  ENVIRONMENT NOTE: pip libewf-python==20240506 builds WITHOUT zlib (read-uncompressed only, NO write). E01 fixtures must be minted with the system libewf via `libewf-tools` ewfacquire -c none. See graphmind memory ref fbb0c3e2."

## Summary

total: 1
passed: 1
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps
