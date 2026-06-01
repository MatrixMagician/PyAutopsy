# Roadmap: PyAutopsy

## Overview

PyAutopsy turns an acquired disk image (plus its logs) into a defensible,
presentation-ready forensic report through a single automated Python/Linux CLI
built on The Sleuth Kit (pytsk3). The journey is dictated by forensic
soundness: a read-only, hash-verified, audited foundation must gate everything,
because integrity and chain-of-custody cannot be retrofitted. From that spine we
walk the filesystem with UTC-everywhere metadata, close an end-to-end MVP
(image -> timeline -> HTML+JSON report) early, then layer the headline forensic
capabilities — deleted-file recovery with honest confidence tiers, known-file
filtering, log parsing into a shared event model, the super-timeline, and
search — onto the proven, normalized SQLite store. Every phase is an MVP vertical
slice that produces something demonstrable and defensible.

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Forensic Foundation** - Read-only ingest (raw/dd + E01), source hash verify, case store, safe-extraction jail, COC + audit log (completed 2026-05-30)
- [x] **Phase 2: Filesystem Walk & Metadata** - Walk ext4/NTFS/FAT yielding per-file inventory, UTC MACB times, owner/perms, per-file hashes, type-by-signature (completed 2026-05-31)
- [x] **Phase 3: Timeline & MVP Report** - Chronological timeline + deterministic HTML/JSON report from one command (closes image -> report MVP) (completed 2026-05-31)
- [x] **Phase 4: Deleted Recovery & Known-File Filtering** - Recover deleted/orphan files with confidence tiers; filter against NSRL + custom hash sets (completed 2026-05-31)
- [x] **Phase 5: Log Parsing, Super-Timeline & Search** - Parse Linux logs into a shared event model, merge into a UTC super-timeline, keyword/IOC search (completed 2026-05-31)

## Phase Details

### Phase 1: Forensic Foundation

**Goal**: An examiner can ingest a raw/dd or E01 image entirely read-only, prove the source was never modified, and have every action recorded — establishing the integrity spine all later analysis writes into.
**Mode:** mvp
**Depends on**: Nothing (first phase)
**Requirements**: INGEST-01, INGEST-02, INGEST-03, INGEST-04, REPORT-01, REPORT-02
**Success Criteria** (what must be TRUE):

  1. Examiner runs `pyautopsy ingest <image> --case ...` on a raw/dd or E01 image and a SQLite case store is created with the image opened read-only (never mounted)
  2. Tool computes MD5 + SHA-256 of the source, compares against a supplied acquisition hash when provided, and re-verifies the source hash at end of run — failing loudly on any mismatch
  3. Case/chain-of-custody metadata (case ID, examiner, evidence ID, acquisition source, tool + TSK versions, timestamps) is recorded in the case store
  4. An append-only audit log records inputs, hashes, parameters, tool versions, start/end times, and errors, written only to the separate case directory
  5. The safe-extraction utility rejects path-traversal (Zip Slip), symlink escape, and decompression-bomb inputs (size/ratio/depth/count limits) on a malicious-archive fixture

**Plans**: 5 plansPlans:
**Wave 1**

- [x] 01-00-PLAN.md — Wave 0: project scaffold, src layout, pytest infra, UTC helper, fixtures, failing end-to-end ingest test (D-13, D-10)
- [x] 01-01-PLAN.md — Case store (SQLite, typed+JSON-attributes schema) + append-only JSONL audit log (REPORT-01, REPORT-02)
- [x] 01-02-PLAN.md — Single native seam (pytsk3/pyewf read-only open) + single-pass MD5/SHA-256 integrity + re-verify + read-only guarantee (INGEST-01/02/03)
- [x] 01-03-PLAN.md — Hardened safe_extract jail vs Zip Slip / symlink / decompression bombs (INGEST-04, phase security gate)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 01-04-PLAN.md — Ingest orchestrator + Typer `pyautopsy ingest` CLI; closes the Walking Skeleton + reproducibility seed

### Phase 2: Filesystem Walk & Metadata

**Goal**: An examiner gets a complete, normalized inventory of every file on supported filesystems with UTC-correct timestamps and per-file hashes — the second source-of-truth that feeds the timeline.
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: META-01, META-02, META-03, META-04, META-05
**Success Criteria** (what must be TRUE):

  1. Tool walks an ext4, NTFS, or FAT image and inventories every file with path, size, inode/MFT address, and allocated/unallocated status, recorded as normalized rows in the case store
  2. MACB timestamps are captured per file as tz-aware UTC (ISO-8601 with explicit offset), with original timezone and timestamp source recorded; no naive/local-time datetimes exist in the pipeline
  3. Ownership (UID/GID) and permission/mode bits are recorded per file
  4. MD5, SHA-1, and SHA-256 are computed per file during the walk in a single streaming pass
  5. File type is identified by content signature (not extension), and encrypted/unsupported volumes are reported as an explicit known-limitation finding rather than producing empty or garbage results

**Plans**: 4 plans

Plans:
**Wave 0**

- [x] 02-00-PLAN.md — Wave 0 scaffold: python-magic dep + filetype.py binding guard, ext4/NTFS/FAT32/partitioned fixtures, executable D-14 seam allowlist test, failing META-01..05 + D-20 + read-only stubs (D-14, D-19)

**Wave 1** *(blocked on Wave 0)*

- [x] 02-01-PLAN.md — Walk slice: files + volume_limitations schema, filesystem.py FS seam, walk orchestrator + `pyautopsy walk` CLI — inventory every entry incl. deleted, volume tagging, D-20 limitations, read-only (META-01, D-14/D-15/D-18/D-20)

**Wave 2** *(blocked on Wave 1)*

- [x] 02-02-PLAN.md — MACB → tz-aware UTC ISO-8601 (FAT local-time flagged, zero→None, no-naive invariant) + UID/GID/mode (META-02, META-03, D-16)

**Wave 3** *(blocked on Wave 2)*

- [x] 02-03-PLAN.md — Per-file single-pass MD5+SHA-1+SHA-256 (empty sentinels, --max-hash-size) + content-signature file typing (META-04, META-05, D-17/D-19)

### Phase 3: Timeline & MVP Report

**Goal**: An examiner runs one command and gets a complete, reproducible forensic report (human-readable + structured) from a disk image — closing the end-to-end MVP vertical slice and proving the spine before more producers are added.
**Mode:** mvp
**Depends on**: Phase 2
**Requirements**: TIME-01, REPORT-03, REPORT-04, CLI-01, CLI-02
**Success Criteria** (what must be TRUE):

  1. Tool builds a chronological timeline (bodyfile/mactime style) from filesystem MACB metadata, UTC-ordered with explicit offsets
  2. Tool generates a human-readable HTML/Markdown report containing case/COC, methodology + tool/TSK versions, findings, evidence hashes, timeline, and a limitations section (no overclaiming)
  3. Tool emits a structured machine-readable JSON report alongside the human-readable report
  4. Examiner runs the full analysis as a single command (`pyautopsy analyze <image> --case ...`) producing the complete report set
  5. Two runs on the same fixture image produce byte-identical analytical report bodies (run metadata segregated), with TSK/tool versions pinned and recorded

**Plans**: 4 plans
**UI hint**: yes

Plans:
**Wave 0**

- [x] 03-00-PLAN.md — Contract surface + RED scaffold: timeline_events table/model + store CRUD (D-23/D-24/D-26), jinja2 dep (D-22), failing tests for all 5 reqs

**Wave 1** *(blocked on Wave 0)*

- [x] 03-01-PLAN.md — Timeline producer: MACB explosion FileRow → timeline_events (TIME-01, D-24)

**Wave 2** *(blocked on Wave 1)*

- [x] 03-02-PLAN.md — Reporter: deterministic body + JSON (full timeline) + Jinja2 HTML (autoescape, bounded D-27, D-28 findings) (REPORT-03/04, D-22/D-25)

**Wave 3** *(blocked on Wave 2)*

- [x] 03-03-PLAN.md — `analyze` orchestrator + CLI command + byte-identical reproducibility test (CLI-01, CLI-02, D-21)

### Phase 4: Deleted Recovery & Known-File Filtering

**Goal**: An examiner can recover deleted and orphaned files with honest, filesystem-aware confidence labeling, and cut noise by filtering files against NSRL and custom hash sets — the headline forensic capability layered onto the proven spine.
**Mode:** mvp
**Depends on**: Phase 3
**Requirements**: RECOV-01, RECOV-02, RECOV-03, FILTER-01
**Success Criteria** (what must be TRUE):

  1. Tool enumerates and recovers deleted files where metadata/data remain intact, writing them as recovered `files` rows with source offset/inode and per-file hashes
  2. Orphan files (deleted files whose parent directory is gone) are reported separately
  3. Each recovered file is labeled with a confidence tier (metadata-intact vs journal vs signature-carving / partial-overwritten), with per-filesystem caveats and overwrite detection — never asserting "the user deleted this"
  4. Tool filters files against NSRL RDS and user-supplied custom hash sets (allow/block lists), surfacing matches as "known" rather than a good/bad verdict

**Plans**: 4 plans

Plans:
**Wave 0**

- [x] 04-00-PLAN.md — Wave 0 scaffold: RED test stubs (test_recover.py, test_knownfiles.py) + deterministic fixtures (orphan/overwritten ext4, resident NTFS, FILE/METADATA NSRL DBs) with ground-truth constants (RECOV-01..03, FILTER-01)

**Wave 1** *(blocked on Wave 0)*

- [x] 04-01-PLAN.md — Recovery vertical slice: filesystem.py seam helpers (recover_meta/allocated_data_blocks) → additive recovery schema/store methods → core/recover.py orchestrator → `pyautopsy recover` CLI → Recovered/Orphan report sections (RECOV-01/02/03, D-29..D-35)

**Wave 2** *(blocked on Wave 1)*

- [x] 04-02-PLAN.md — Known-file filtering vertical slice: filter/nsrl.py (read-only probe, UPPERCASE/variant) + filter/hashsets.py → known_file_matches store methods → core/knownfiles.py post-walk pass → Known-File report section (FILTER-01, D-36..D-39)

**Wave 3** *(blocked on Waves 1+2)*

- [x] 04-03-PLAN.md — Integration: opt-in recover/filter wiring in `analyze` + --recover/--nsrl/--hash-set flags + reproducibility/read-only/seam-allowlist tests + _MVP_LIMITATIONS honesty update (D-40/D-41/D-42)

**Gap closure** *(post-UAT fix)*

- [x] 04-04-PLAN.md — Fix root-level deleted-file misclassification: walk_fs tags root entries with fs.info.root_inum so root deletions classify as Recovered (not falsely Orphan); reserve None for genuine no-dir-link orphans; root-deletion regression fixture + test (FAT + ext4) (RECOV-02 gap)

### Phase 5: Log Parsing, Super-Timeline & Search

**Goal**: An examiner sees filesystem and log evidence merged into one UTC-ordered super-timeline and can search across allocated, unallocated, and file content — completing the full "image + logs -> defensible report" pipeline.
**Mode:** mvp
**Depends on**: Phase 4
**Requirements**: LOG-01, LOG-02, LOG-03, LOG-04, TIME-02, SEARCH-01, SEARCH-02
**Success Criteria** (what must be TRUE):

  1. Tool parses Linux authentication logs (`auth.log`/`secure`) from the evidence image, surfacing logins, SSH, sudo, and failed-auth events, with rotated/compressed sets reassembled and year/timezone inferred-and-flagged
  2. Tool parses syslog/messages (service, kernel, cron, error events) and per-user shell history (`.bash_history`/`.zsh_history`), noting tamperability and log completeness as findings
  3. All parsed log events are normalized into the shared forensic-event model (timestamp, source, type, actor, action, outcome, evidence-ref) identical in shape to filesystem events
  4. Tool builds a super-timeline merging filesystem metadata and parsed log events into one UTC-sorted chronological view
  5. Examiner can run literal and regex keyword searches across allocated content, unallocated space, and file content, and match against supplied IOC lists and known-bad hash sets — reporting hits with file and offset

**Plans**: 7 plans (5 shipped + 2 gap-closure)

Plans:
**Wave 0**

- [x] 05-00-PLAN.md — Wave 0 scaffold: committed log/search fixtures + RED test stubs (LOG/SEARCH/TIME) + D-43 no-new-deps guard

**Wave 1** *(blocked on Wave 0)*

- [x] 05-01-PLAN.md — Auth slice: log/ scaffolding (registry/discover/timeresolve/normalize) + auth.log parser + core/logs.py + `pyautopsy logs` CLI (LOG-01, LOG-04, TIME-02; D-45/D-46/D-47)

**Wave 2** *(blocked on Wave 1; 05-02 and 05-03 run in parallel)*

- [x] 05-02-PLAN.md — syslog/messages + shell-history parsers registering into the shared pipeline (LOG-02, LOG-03; D-44 tamperability findings)
- [x] 05-03-PLAN.md — Search slice: iter_unallocated_blocks seam + additive search_hits store + streaming literal/regex + IOC/known-bad-hash + `pyautopsy search` CLI (SEARCH-01, SEARCH-02; D-49)

**Wave 3** *(blocked on Waves 1+2)*

- [x] 05-04-PLAN.md — Integration: opt-in `analyze --logs/--search` + report sections + super-timeline (TIME-02) + CLI-02/CR-01 reproducibility tests (D-48)

**Gap closure** *(post-UAT; both plans independent, parallel)*

- [ ] 05-05-PLAN.md — G-2 (MAJOR): thread D-44 shell-history tamperability + D-45 log-completeness findings through run_logs into the case and render them in the report log_findings disclosures (LOG-03/LOG-02/LOG-01)
- [ ] 05-06-PLAN.md — G-1 (minor): reconcile fixture mtime anchor vs ground-truth sidecar year (D-46), Path B — no image rebuild (TIME-02)

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Forensic Foundation | 5/5 | Complete    | 2026-05-30 |
| 2. Filesystem Walk & Metadata | 4/4 | Complete    | 2026-05-31 |
| 3. Timeline & MVP Report | 4/4 | Complete    | 2026-05-31 |
| 4. Deleted Recovery & Known-File Filtering | 5/5 | Complete    | 2026-05-31 |
| 5. Log Parsing, Super-Timeline & Search | 5/5 | Complete    | 2026-05-31 |
