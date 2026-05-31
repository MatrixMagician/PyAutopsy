---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: executing
stopped_at: Phase 3 UI-SPEC approved
last_updated: "2026-05-31T12:46:51.342Z"
last_activity: 2026-05-31 -- Phase 3 execution started
progress:
  total_phases: 5
  completed_phases: 2
  total_plans: 13
  completed_plans: 11
  percent: 40
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-30)

**Core value:** Turn a raw disk image (and associated logs) into a defensible, presentation-ready forensic report — with deleted-file recovery and metadata analysis — through a single automated Python workflow.
**Current focus:** Phase 3 — Timeline & MVP Report

## Current Position

Phase: 3 (Timeline & MVP Report) — EXECUTING
Plan: 3 of 4
Status: Ready to execute
Last activity: 2026-05-31 -- Phase 3 execution started

Progress: [████████░░] 80%

## Performance Metrics

**Velocity:**

- Total plans completed: 9
- Average duration: — min
- Total execution time: 0.0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1 | 5 | - | - |
| 2 | 4 | - | - |

**Recent Trend:**

- Last 5 plans: —
- Trend: —

*Updated after each plan completion*
| Phase 01 P00 | 5 | 3 tasks | 13 files |
| Phase 01 P01 | 8 | 2 tasks | 8 files |
| Phase 01 P02 | 9 | 2 tasks | 8 files |
| Phase 01 P03 | 4 | 2 tasks | 2 files |
| Phase 03-timeline-mvp-report P00 | 20min | 2 tasks | 10 files |
| Phase 03 P01 | ~10min | 1 tasks | 2 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Roadmap]: Drive libtsk directly via pytsk3 — do NOT build on Autopsy the application (Jython 2.7 cannot load native libs); same engine, full Python 3 ecosystem.
- [Roadmap]: Normalized SQLite case store is the architectural spine; all producers write rows, the reporter only reads.
- [Roadmap]: Forensic soundness (read-only, hashing, UTC-everywhere, audit, safe extraction) is gated in Phase 1 and enforced every phase — it cannot be retrofitted.
- [Roadmap]: v1 recovery scoped to ext4/NTFS/FAT + raw/dd/E01; exFAT/HFS+/APFS gated behind a runtime capability probe (deferred to v2).
- [Phase ?]: 01-00: hatchling dynamic version makes __version__ the single source of truth
- [Phase ?]: 01-00: committed deterministic 64 KiB tiny_raw.dd fixture instead of mkfs-at-test-time (A3)
- [Phase ?]: 01-00: kept timezone.utc idiom (ruff UP017 ignored) per D-10/PITFALLS P4
- [Phase 1]: 01-01: CaseStore is the sole DB writer abstraction — no raw SQL outside src/pyautopsy/case/store.py
- [Phase 1]: 01-01: run_log table present as optional SQLite mirror target (D-09); JSONL audit log stays authoritative
- [Phase 1]: 01-01: tool version via importlib.metadata.version('pyautopsy') with __version__ fallback for uninstalled checkouts
- [Phase 1]: 01-01: audit writer rejects reserved action/ts keys to prevent shadowing the UTC stamp (tamper-evidence)
- [Phase 1]: 01-02: single native seam realised — evidence/image.py is the SOLE pytsk3/pyewf importer (grep gate enforces D-06); pyewf imported lazily with an actionable install-hint error
- [Phase 1]: 01-02: mounted-source guard refuses a source path that IS a mountpoint (portable on hosts with separate /tmp,/home), not any file merely residing under a mount (P1)
- [Phase 1]: 01-02: acquisition algorithm selected by supplied hash hex length (32->md5, 64->sha256); unrecognised length raises IntegrityError so an uncomparable hash never silently passes
- [Phase 1]: 01-02: mypy [[overrides]] ignore_missing_imports for stub-less native bindings pytsk3/pyewf, scoped to the seam; TSK_VERSION_STR (4.15.0) recorded for the COC record (A1)
- [Phase 1]: 01-03: safe_extract confines on the ORIGINAL stored member name BEFORE the stdlib data filter — data_filter silently relativizes /etc/x to etc/x, masking an absolute-path tampering signal, so we REJECT instead
- [Phase 1]: 01-03: filter='data' (public tarfile.data_filter) applied per tar member as defense-in-depth; realpath confinement + hand-written bomb caps are the primary controls (filter='data' does NOT stop bombs)
- [Phase 1]: 01-03: bomb caps via a streamed running uncompressed-byte counter that aborts a total-size bomb mid-write; ExtractionLimits defaults 1GiB/256MiB/100x/10000/depth3, all overridable
- [Phase ?]: Phase 3 timeline events: actor encoded as uid=<n>,gid=<n>; action/outcome reserved for Phase 5 log producers (D-23)
- [Phase ?]: D-26 total order defined only in CaseStore.get_timeline_events ORDER BY; builder/reporter never re-sort or write raw SQL
- [Phase ?]: Timeline builder uses canonical _explode transform + exported explode alias; ts_utc copied verbatim (no re-derivation), writes via store transaction, no native imports/raw SQL (TIME-01)

### Pending Todos

[From .planning/todos/pending/ — ideas captured during sessions]

None yet.

### Blockers/Concerns

[Issues that affect future work]

- Native deps (libtsk/libewf/libfuzzy/libsystemd) are the #1 install failure mode — design the install story (Containerfile + documented system packages) in Phase 1.
- pytsk3 FS-capability matrix (exFAT/HFS+/APFS, encrypted volumes) needs a build-time spike in Phase 2; gate unsupported FS behind a runtime probe, fail clearly.

## Deferred Items

Items acknowledged and carried forward from previous milestone close:

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| *(none)* | | | |

## Session Continuity

Last session: 2026-05-31T12:46:36.241Z
Stopped at: Phase 3 UI-SPEC approved
Resume file: .planning/phases/03-timeline-mvp-report/03-UI-SPEC.md
