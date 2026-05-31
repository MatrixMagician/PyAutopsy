---
phase: 05-log-parsing-supertimeline-search
plan: 02
subsystem: log-parsing
tags: [syslog, messages, rfc3164, rfc5424, shell-history, bash, zsh, tamperability, log-02, log-03, ext-01, d-44, d-46]
requires:
  - "05-01: LogParser Protocol + ParsedRecord + declared-order registry (EXT-01)"
  - "05-01: shared RFC3164/RFC5424 grammar (log/_grammar.parse_line)"
  - "05-01: timeresolve (D-46) + normalize (LOG-04) + core/logs.run_logs orchestrator"
provides:
  - "LOG-02 SyslogParser (syslog/messages: kernel/cron/service taxonomy + error-level annotation)"
  - "LOG-03 ShellHistoryParser (bash/zsh) + ShellHistoryResult (records + tamperability finding)"
  - "two more EXT-01 registrants flowing through the unchanged core/logs.py pipeline"
affects:
  - "the super-timeline now carries syslog + shell-history events alongside auth (TIME-02)"
tech-stack:
  added: []
  patterns:
    - "parser mirrors log/auth.py: parse(text)->records, self-registers at import (EXT-01)"
    - "shell history returns a result object (records + findings) iterable over its records"
key-files:
  created:
    - src/pyautopsy/log/shell_history.py
  modified:
    - src/pyautopsy/log/syslog.py
decisions:
  - "syslog action taxonomy is program-based (kernel/cron/service); error-level is a non-authoritative outcome annotation over the message text — observed-line only, never inferred intent"
  - "shell-history parsers self-register at import time (mirroring auth) rather than wiring an import into core/logs.py — keeps the orchestrator UNCHANGED (EXT-01) and within the two-file plan scope"
  - "no-per-line-timestamp bash lines carry ts_basis='file-mtime-fallback; no per-line timestamp' (matching the orchestrator's existing fallback basis string); the UTC anchor is applied downstream by run_logs (D-46), never invented in the parser"
  - "tamperability finding (D-44) rides on a ShellHistoryResult object alongside the records rather than being smuggled into a record field"
metrics:
  duration: ~13m
  completed: 2026-05-31
  tasks: 2
  files: 2
---

# Phase 05 Plan 02: Log Parsers — syslog/messages (LOG-02) & shell-history (LOG-03) Summary

Added the two remaining Wave-2 log parsers — a syslog/messages parser (kernel/cron/service taxonomy with an honest error-level annotation, reusing the shared RFC3164/RFC5424 grammar) and a bash/zsh shell-history parser that handles embedded epochs, flags the no-per-line-timestamp fallback, and surfaces a tamperability finding (D-44) — both self-registering into the EXT-01 registry so the unchanged `core/logs.py` orchestrator picks them up.

## What Was Built

- **`src/pyautopsy/log/syslog.py` (LOG-02):** `SyslogParser` implementing the `LogParser` protocol exactly like `auth.py`. Reuses `log/_grammar.parse_line` (no divergent regex). A small program-based `_classify` maps `kernel` -> `action="kernel"`, `CRON`/`cron`/`crond` -> `action="cron"`, anything else -> `action="service"`; an error-level regex over the message body adds a non-authoritative `outcome="error"` annotation. Unmatched lines still become events carrying the raw message; blank lines skipped. Emits `ParsedRecord`s with `source="syslog"` downstream. Self-registers at import time.
- **`src/pyautopsy/log/shell_history.py` (LOG-03):** `ShellHistoryParser` + a `ShellHistoryResult` dataclass (records + findings, iterable over its records). Detects zsh extended `: <start>:<elapsed>;cmd` (embedded start epoch -> `ParsedRecord.epoch`) and bash `#<epoch>` markers (applied to the following command). Commands with neither form get `ts_basis="file-mtime-fallback; no per-line timestamp"` rather than an invented time. Owning user derived from `/home/<user>` -> `actor="user=<name>"`, else `None` (never `"user=None"`, WR-05). Always surfaces a tamperability finding (D-44, observed-fact only). Self-registers at import time.

## Tasks Completed

1. **Task 1: syslog/messages parser (LOG-02)** — `a38ec5b` (feat)
2. **Task 2: shell-history parser + tamperability finding (LOG-03)** — `53864c4` (feat)

## Verification

- `tests/test_logs.py::test_syslog_events` — PASS (systemd/kernel/CRON/nginx programs extracted; error line preserved)
- `tests/test_logs.py::test_shell_history_tamperability` — PASS (bash no-ts fallback flagged; tamperability finding present; zsh embedded epoch read)
- `tests/test_logs.py` full — **8 passed** (was 6 passing + 2 RED in 05-01; both now GREEN)
- `tests/test_seam_allowlist.py tests/test_no_new_deps.py` — **4 passed** (D-14 seam + D-43 no-new-dep invariants hold)
- `ruff check src/pyautopsy/log` + `mypy src/pyautopsy/log` — clean
- `core/logs.py` UNCHANGED (EXT-01 verified — no diff vs HEAD; parsers add via registry + import-time registration only)
- Full suite: **199 passed, 4 failed** — the 4 failures are the out-of-scope 05-03 search RED stubs (`test_streaming_search_all_regions`, `test_boundary_spanning_match`, `test_ioc_and_hash_hits`, `test_iter_unallocated_blocks_seam`) running in parallel on disjoint files (search/ + evidence/filesystem.py). No in-scope regression.

## Deviations from Plan

None — plan executed exactly as written. Both parsers self-register at import time (the established `auth.py` pattern), so no orchestrator or `__init__.py` edit was needed and the plan's two-file `files_modified` scope held exactly.

## Threat Surface

No new security-relevant surface beyond the plan's `<threat_model>`. T-05-02-01 (malicious content) is mitigated by decoding evidence as DATA-only (the orchestrator already decodes utf-8/errors="replace"); T-05-02-02 (history-as-chronology) is mitigated by the explicit tamperability + no-per-line-timestamp findings; T-05-02-03 (inferred tz/year) reuses the Wave-1 timeresolve D-46 flagging; T-05-02-SC (installs) — zero package installs, `test_no_new_deps.py` stays GREEN.

## Self-Check: PASSED

- FOUND: src/pyautopsy/log/syslog.py
- FOUND: src/pyautopsy/log/shell_history.py
- FOUND commit: a38ec5b
- FOUND commit: 53864c4
