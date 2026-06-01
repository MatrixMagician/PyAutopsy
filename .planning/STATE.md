---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: executing
stopped_at: Completed 05-06-PLAN.md (G-1 gap closure)
last_updated: "2026-06-01T10:38:15.117Z"
last_activity: 2026-06-01 -- 05-06 gap closure (G-1) executed
progress:
  total_phases: 5
  completed_phases: 5
  total_plans: 25
  completed_plans: 25
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-30)

**Core value:** Turn a raw disk image (and associated logs) into a defensible, presentation-ready forensic report — with deleted-file recovery and metadata analysis — through a single automated Python workflow.
**Current focus:** Phase 05 — log-parsing-supertimeline-search

## Current Position

Phase: 05 (log-parsing-supertimeline-search) — all 7 plans complete (incl. G-1/G-2 gap closures)
Plan: 7 of 7 (05-05 G-2 done; 05-06 G-1 done)
Status: Phase 05 plans complete — ready for verification / phase close
Last activity: 2026-06-01 -- 05-06 gap closure (G-1) executed

Progress: [██████████] 100%

## Performance Metrics

**Velocity:**

- Total plans completed: 23
- Average duration: — min
- Total execution time: 0.0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 5 | - | - |
| 02 | 4 | - | - |
| 03 | 4 | - | - |
| 04 | 5 | - | - |
| 05 | 5 | - | - |

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
| Phase 03-timeline-mvp-report P02 | 5min | 2 tasks | 5 files |
| Phase 03-timeline-mvp-report P03 | 25m | 2 tasks | 5 files |
| Phase 04 P00 | 60 | 2 tasks | 9 files |
| Phase 04 P04-01 | ~75min | 3 tasks | 8 files |
| Phase 04 P04-02 | 35min | 2 tasks | 10 files |
| Phase 04 P04-03 | 30 | 2 tasks | 5 files |
| Phase 05 P00 | 7min | 2 tasks | 8 files |
| Phase 05 P01 | 9min | 2 tasks | 11 files |
| Phase 05 P02 | 13m | 2 tasks | 2 files |
| Phase 05 P03 | 25min | 2 tasks | 13 files |
| Phase 05 P04 | 35min | 2 tasks | 5 files |
| Phase 05 P05 (G-2) | ~22min | 3 tasks | 12 files |
| Phase 05 P06 (G-1) | ~18min | 2 tasks | 3 files |

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
- [Phase ?]: Reporter: one deterministic assemble_report_body dict (no wall-clock) feeds both JSON (full timeline) and HTML (in-process body[:cap] slice + honest Showing N of M); run metadata segregated to build_run_metadata (D-25/W-1/W-2)
- [Phase ?]: report.html + report.json carry zero run metadata (whole-file byte-deterministic); jinja2 autoescape neutralizes evidence strings; outputs confined to case_dir/reports/ via _is_within
- [Phase ?]: analyze removes wall-clock COC timestamps from the report body — run metadata stays in case.db + run_metadata.json sidecar, keeping report.json/html byte-deterministic (CLI-02/W-1)
- [Phase ?]: report.html.j2 uses item access body.integrity[copy] — attribute access resolved the dict built-in .copy method, leaking a memory address
- [Phase 04]: 04-01: recovery enumerates deleted inodes via a new seam helper (iter_deleted_inodes: directory-walk + inode-range scan), not a prior walk inventory — required for standalone ingest->recover and NTFS broken name->meta links
- [Phase 04]: 04-01: orphan-ness = parent-gone (parent_addr not in allocated-inode set) OR the TSK ORPHAN meta flag, since the ext4 orphan fixture leaves the meta flag unset
- [Phase ?]: 04-02: NSRL probe opens DB read-only (mode=ro + PRAGMA query_only), FILE/METADATA from a fixed allowlist, UPPERCASE-normalized (Pitfall 4), parameterized SQL only (D-36/D-37); neutral known annotations never good/bad (D-38); dedicated known_file_matches table keeps CaseStore sole writer with a store-owned report total order (D-41)
- [Phase ?]: 04-03: analyze recovery+filtering are opt-in (D-40); default analyze stays Phase-3 byte-identical
- [Phase ?]: 04-03: _MVP_LIMITATIONS disclaimer is conditional — verbatim Phase-3 text when nothing ran, rebuilt honestly when recovery/filtering ran (D-28/D-32)
- [Phase ?]: 04-03: CLI carries hash-list sense via paired --hash-set-allow/--hash-set-block options (deterministic order, D-41)
- [Phase ?]: 05-02: shell-history/syslog parsers self-register at import time (mirroring auth) so core/logs.py stays unchanged (EXT-01)
- [Phase ?]: [Phase 05]: 05-03: iter_unallocated_blocks = COMPLEMENT of allocated_data_blocks read raw via the byte seam; block_size(fs) seam helper maps indices to absolute offsets (all pytsk3 in filesystem.py, D-14)
- [Phase ?]: [Phase 05]: 05-03: search_hits is the only new schema item (additive, D-47 timeline_events untouched); store-owned total order volume_id,volume_offset,byte_offset,term,id (D-41)
- [Phase ?]: [Phase 05]: 05-03: boundary-spanning dedup emits a match only when it ends past the carried overlap (exactly-once, Pitfall 5); ReDoS-bounded regex; search reuses filter/hashsets verbatim (no new dep, D-43)
- [Phase ?]: [Phase 05]: 05-03: known-bad-hash hits persisted BOTH as KnownMatch and term_kind=hash SearchHit so they surface by file in unified search results
- [Phase ?]: Wave-3 integration: run_analyze --logs/--search opt-in arms run after build_timeline so run_logs fs-event backfill is a no-op; super-timeline total read from get_timeline_events (TIME-02, no new ORDER BY)
- [Phase ?]: CR-01 locked via a direct store-level NULL-meta tied-log-event tiebreak test (source/actor/id), since run_logs surfaces only auth events on the current fixture
- [Phase 05]: 05-05 (G-2): D-44/D-45 honesty findings now reach the report — additive log_findings table (mirrors volume_limitations D-20; timeline_events untouched D-47), threaded through run_logs in the existing single transaction (WR-01), rendered as log_findings.disclosures (json+html); default analyze path empties to [] keeping report bytes identical (D-48)
- [Phase 05]: 05-05: ShellHistoryParser.findings_for additive accessor reaches the dropped tamperability finding WITHOUT changing the EXT-01 LogParser.parse record-only protocol; tamperability detail persisted verbatim (observed-fact, never intent, D-44)
- [Phase 05]: 05-06 (G-1): Path B fixture/sidecar reconciliation — retargeted LOG_SEARCH_YEAR/PREV_YEAR + log_search_groundtruth.json to 2023/2022 (the _EXT4_FAKE_TIME=1700000000 mtime anchor D-46 yields); image bytes + sha256 6e41afad...079b0 UNCHANGED so the UAT-test-11 read-only baseline needs no lockstep
- [Phase 05]: 05-06: regression guard test_groundtruth_year_matches_fixture_mtime pins year_inferred (the D-46 RFC3164 year), NOT the tz-converted ts_utc calendar year — a Dec 31 ET line crosses to 2024-01-01Z, a tz artifact whose year_inferred is correctly 2023

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

Last session: 2026-06-01T10:38:15.113Z
Stopped at: Completed 05-06-PLAN.md (G-1 gap closure)
Resume file: None
