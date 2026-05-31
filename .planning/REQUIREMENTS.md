# Requirements: PyAutopsy

**Defined:** 2026-05-30
**Core Value:** Turn a raw disk image (and associated logs) into a defensible, presentation-ready forensic report — with deleted-file recovery and metadata analysis — through a single automated Python workflow.

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases. Scope = the
table-stakes "image → defensible report" pipeline from research/FEATURES.md MVP.

### Ingestion & Integrity

- [x] **INGEST-01**: User can ingest a disk image (raw/dd and E01/EWF) for analysis
- [x] **INGEST-02**: Tool verifies source image integrity by computing MD5 + SHA-256 and comparing against a supplied acquisition hash when provided
- [x] **INGEST-03**: Tool guarantees evidence is never modified — source opened read-only, never mounted, all output written to a separate case directory, source hash re-verified at end of run
- [x] **INGEST-04**: Tool extracts/parses evidence and archives safely, rejecting path-traversal (Zip Slip) and decompression-bomb inputs

### Metadata Analysis

- [x] **META-01**: Tool walks the filesystem and inventories every file with path, size, inode/MFT address, and allocated/unallocated status (ext4, NTFS, FAT)
- [x] **META-02**: Tool records MACB timestamps per file, normalized to UTC, with original timezone and timestamp source captured
- [x] **META-03**: Tool records ownership (UID/GID) and permission/mode bits per file
- [x] **META-04**: Tool computes per-file hashes (MD5, SHA-1, SHA-256) during the filesystem walk
- [x] **META-05**: Tool identifies file type by content signature (not extension)

### Deleted File Recovery

- [ ] **RECOV-01**: Tool enumerates and recovers deleted files where metadata/data remain intact
- [ ] **RECOV-02**: Tool reports orphan files (deleted files whose parent directory is gone) separately
- [ ] **RECOV-03**: Tool labels each recovered file with a confidence level (intact vs partial/overwritten)

### Known-File Filtering

- [ ] **FILTER-01**: Tool filters known files against NSRL RDS and user-supplied custom hash sets (allow/block lists), surfacing matches as "known" rather than a good/bad verdict

### Log Analysis

- [ ] **LOG-01**: Tool parses Linux authentication logs (`auth.log` / `secure`) from the evidence image, surfacing logins, SSH, sudo, and failed-auth events
- [ ] **LOG-02**: Tool parses syslog/messages for service, kernel, cron, and error events
- [ ] **LOG-03**: Tool parses shell history (`.bash_history` / `.zsh_history`) per user, noting tamperability
- [ ] **LOG-04**: Tool normalizes all parsed log events into a shared forensic-event model (timestamp, source, type, actor, action, outcome, evidence-ref)

### Timeline

- [x] **TIME-01**: Tool builds a chronological timeline from filesystem MACB metadata (bodyfile/mactime style)
- [ ] **TIME-02**: Tool builds a super-timeline merging filesystem metadata and parsed log events into one UTC-sorted chronological view

### Search & Matching

- [ ] **SEARCH-01**: User can run literal and regex keyword searches across allocated content, unallocated space, and file content
- [ ] **SEARCH-02**: Tool matches files and content against supplied IOC lists and known-bad hash sets, reporting hits with file and offset

### Reporting & Case Management

- [x] **REPORT-01**: Tool records case / chain-of-custody metadata (case ID, examiner, evidence ID, acquisition source, tool + versions, timestamps)
- [x] **REPORT-02**: Tool writes an append-only audit log of its actions (inputs, hashes, parameters, tool versions, start/end times, errors)
- [x] **REPORT-03**: Tool generates a human-readable report (HTML/Markdown) with case/COC, methodology + tool versions, findings, evidence hashes, timeline, and exhibits
- [x] **REPORT-04**: Tool emits a structured machine-readable JSON report alongside the human-readable report

### CLI & Pipeline

- [x] **CLI-01**: User can run the full analysis as a single command (`pyautopsy analyze <image> --case ...`) producing the complete report
- [x] **CLI-02**: Tool produces deterministic, reproducible output (stable ordering, pinned tool versions recorded in the report)

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap. (From FEATURES.md "Add After Validation / Future Consideration.")

### Recovery & Carving

- **CARVE-01**: File carving from unallocated space (wrap photorec/scalpel/foremost)
- **RECOV-04**: exFAT / HFS+ / APFS deleted-file recovery (gated on linked TSK build)

### Extended Log Coverage

- **LOG-05**: Parse systemd journal (binary), auditd, and wtmp/btmp/lastlog
- **LOG-06**: Parse web/server logs (apache/nginx) and package logs (dpkg/apt/dnf)

### Analyst Aids

- **ANOM-01**: Timeline anomaly / timestomp surfacing ($SI vs $FN mismatch, future/out-of-order timestamps)
- **ANOM-02**: Extension-vs-content mismatch and suspicious-file flagging
- **RULE-01**: YARA rule pack support
- **SEARCH-03**: Full-text search indexing for fast keyword search on large images

### Interoperability

- **JSON-01**: CASE/UCO-conformant JSON export
- **DIFF-01**: Report diffing across runs/images
- **CONF-01**: Config-driven runs (YAML/TOML recipes: parsers, hash sets, keyword lists, carving toggles)
- **TIME-03**: plaso integration as an alternative super-timeline backend

## Out of Scope

Explicitly excluded. Documented to prevent scope creep. (Anti-features from research/FEATURES.md.)

| Feature | Reason |
|---------|--------|
| Live / memory forensics (RAM capture, running-process analysis) | Different acquisition model + tooling (Volatility, LiME); not disk/log; huge scope. Point users to Volatility. |
| Malware sandboxing / dynamic analysis / reverse engineering | Requires isolated execution + behavioral instrumentation; verdicts aren't forensic facts. Static YARA/IOC indicators only. |
| Network / packet forensics (PCAP) | Separate domain (Wireshark/Zeek/Suricata), different data model. Parse host logs only. |
| GUI / web interface | Autopsy already provides a GUI; duplicating it abandons the CLI/automation differentiator. Build UIs on the JSON instead. |
| Court-admissibility certification / legal verdicts | Legal determination is the investigator's & court's job; overreach undermines credibility. Produce factual findings + COC, disclaim conclusions. |
| Windows/macOS host support (running the tool there) | v1 targets Linux host. (Analyzing Windows/macOS *images* on Linux remains valid and supported.) |
| Auto "this user is guilty / smoking gun" conclusions | Forensic reports must be neutral and factual; interpretation invites bias challenges. Surface evidence + flags only. |
| Reimplementing TSK carving/parsing primitives | TSK is the trusted, court-tested implementation; reimplementation forfeits credibility. Wrap pytsk3/photorec/plaso. |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| INGEST-01 | Phase 1 | Complete |
| INGEST-02 | Phase 1 | Complete |
| INGEST-03 | Phase 1 | Complete |
| INGEST-04 | Phase 1 | Complete |
| META-01 | Phase 2 | Complete |
| META-02 | Phase 2 | Complete |
| META-03 | Phase 2 | Complete |
| META-04 | Phase 2 | Complete |
| META-05 | Phase 2 | Complete |
| RECOV-01 | Phase 4 | Pending |
| RECOV-02 | Phase 4 | Pending |
| RECOV-03 | Phase 4 | Pending |
| FILTER-01 | Phase 4 | Pending |
| LOG-01 | Phase 5 | Pending |
| LOG-02 | Phase 5 | Pending |
| LOG-03 | Phase 5 | Pending |
| LOG-04 | Phase 5 | Pending |
| TIME-01 | Phase 3 | Complete |
| TIME-02 | Phase 5 | Pending |
| SEARCH-01 | Phase 5 | Pending |
| SEARCH-02 | Phase 5 | Pending |
| REPORT-01 | Phase 1 | Complete |
| REPORT-02 | Phase 1 | Complete |
| REPORT-03 | Phase 3 | Complete |
| REPORT-04 | Phase 3 | Complete |
| CLI-01 | Phase 3 | Complete |
| CLI-02 | Phase 3 | Complete |

**Coverage:**

- v1 requirements: 27 total
- Mapped to phases: 27 ✓
- Unmapped: 0 ✓

**Per-phase counts:**

- Phase 1 (Forensic Foundation): 6 — INGEST-01..04, REPORT-01, REPORT-02
- Phase 2 (Filesystem Walk & Metadata): 5 — META-01..05
- Phase 3 (Timeline & MVP Report): 5 — TIME-01, REPORT-03, REPORT-04, CLI-01, CLI-02
- Phase 4 (Deleted Recovery & Known-File Filtering): 4 — RECOV-01..03, FILTER-01
- Phase 5 (Log Parsing, Super-Timeline & Search): 7 — LOG-01..04, TIME-02, SEARCH-01, SEARCH-02

---
*Requirements defined: 2026-05-30*
*Last updated: 2026-05-30 after roadmap creation (traceability mapped)*
