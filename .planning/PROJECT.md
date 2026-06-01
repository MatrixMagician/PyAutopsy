# PyAutopsy

## What This Is

PyAutopsy is a Python tool for automated digital forensic analysis on Linux. It
ingests disk images and log files, analyzes file metadata, recovers deleted
files, and generates a structured forensic report suitable for evidence
presentation. It wraps The Sleuth Kit's forensic primitives directly via the
`pytsk3` bindings (not the Autopsy GUI app) in an automated, scriptable Python
CLI workflow. As of v1.0 the full "image (+ logs) → defensible report" pipeline
ships behind one `pyautopsy analyze` command.

## Core Value

Turn a raw disk image (and associated logs) into a defensible, presentation-ready
forensic report — with deleted-file recovery and metadata analysis — through a
single automated Python workflow.

## Requirements

### Validated

<!-- Shipped and confirmed valuable. -->

- ✓ Ingest a disk image (raw/dd + E01) read-only via The Sleuth Kit / pytsk3 — Validated in Phase 1 (E01-native path is manual-only, tracked in 01-HUMAN-UAT.md)
- ✓ Preserve evidence integrity (single-pass MD5+SHA-256, acquisition compare, end-of-run re-verify, never-mounted guard, chain-of-custody in SQLite case store, append-only JSONL audit log) — Validated in Phase 1
- ✓ Run on Linux as a command-line tool (`pyautopsy ingest`, Typer CLI) — Validated in Phase 1
- ✓ Analyze file metadata: walk ext4/NTFS/FAT yielding a normalized per-file inventory (path, size, inode/MFT addr, allocated/unallocated status), UTC-correct MACB times, ownership/mode, per-file MD5+SHA-1+SHA-256, and content-signature file typing; encrypted/unsupported volumes recorded as known-limitation findings (`pyautopsy walk`) — Validated in Phase 2 (real partitioned-disk-at-scale and sub-second nano MACB are manual-only, tracked in 02-HUMAN-UAT.md)
- ✓ Build a chronological **filesystem timeline** (bodyfile/mactime-style MACB explosion) persisted into a shared forensic-event model, UTC-ordered with a deterministic total order — Validated in Phase 3 (super-timeline merge with logs remains Phase 5)
- ✓ Generate a **forensic report suitable for evidence presentation** — human-readable HTML (Jinja2) + structured JSON, with case/COC, methodology + pinned tool/TSK versions, findings, evidence hashes, bounded timeline, and a no-overclaiming limitations section, all from a single reproducible `pyautopsy analyze` command (byte-identical analytical bodies across runs) — Validated in Phase 3 (large real-disk run, visual/A4-print, and live acquisition-hash FAIL path are manual-only, tracked in 03-HUMAN-UAT.md; PDF rendering deferred)
- ✓ **Recover deleted and orphaned files** from supported filesystems with honest, filesystem-aware confidence labeling (metadata-intact recovery via the TSK seam; intact vs partial/overwritten tiers from derived allocated-block intersection; orphans reported separately; recovered bytes written to a confined `recovered/` tree and cataloged as hashed `files` rows; never asserting intent), **and cut review noise by filtering files against NSRL RDS + custom allow/block hash sets** surfaced as neutral "known" annotations — opt-in via `pyautopsy recover` and `analyze --recover/--nsrl/--hash-set-*` — Validated in Phase 4 (ext4-journal recovery and signature carving (CARVE-01) deferred; rendered-report visual review + tier-glyph/A4-print are manual-only, tracked in 04-HUMAN-UAT.md)
- ✓ **Parse Linux logs into a shared forensic-event model** — auth.log/secure (logins/SSH/sudo/failed-auth), syslog/messages (service/kernel/cron/error), and per-user shell history — read from the evidence image via the seam, rotated/gz sets reassembled, tz+year inferred-and-flagged (RFC3164→UTC), tamperability + log-completeness surfaced as neutral findings; all normalized identically to filesystem events — Validated in Phase 5 (LOG-01..04; journald/auditd/wtmp = v2 LOG-05)
- ✓ **Merge filesystem + log events into one UTC super-timeline** and **search across allocated, unallocated, and file content** (streaming literal/regex, IOC + known-bad-hash matching, hits reported by file+offset) — via `pyautopsy logs` / `search` and `analyze --logs --search`, default `analyze` staying byte-identical — Validated in Phase 5 (TIME-02, SEARCH-01/02; full-text indexing = v2 SEARCH-03)

### Active

<!-- Current scope. Building toward these. Hypotheses until shipped. -->

v1.0 MVP shipped 2026-06-01 — all v1 requirements validated above. No active
milestone scope; next requirements defined via `/gsd-new-milestone`. Candidate v2
directions tracked in `milestones/v1.0-REQUIREMENTS.md` (## v2 Requirements):
file carving (CARVE-01), journald/auditd/wtmp (LOG-05), web/package logs (LOG-06),
timestomp/anomaly surfacing (ANOM-*), YARA (RULE-01), full-text search (SEARCH-03),
CASE/UCO export (JSON-01), plaso backend (TIME-03).

### Out of Scope

<!-- Explicit boundaries. Includes reasoning to prevent re-adding. -->

- Windows/macOS host support — target platform is Linux only for v1
- GUI / web interface — v1 is CLI/automation focused; Autopsy already provides a GUI
- Live/memory forensics (RAM acquisition, running-process analysis) — disk and log analysis only for v1
- Network/packet forensics — out of initial scope
- Malware reverse engineering / sandboxing — analysis is metadata- and artifact-driven, not behavioral
- Court-admissibility certification — tool aids investigation; legal admissibility is the investigator's responsibility

## Context

- **Domain:** Digital forensics / incident response. Output is used as part of a
  forensic investigation and may support evidence presentation.
- **Foundation:** Built on Autopsy and The Sleuth Kit (TSK), the de-facto
  open-source forensic toolkit. Python bindings (`pytsk3`) expose TSK
  primitives for filesystem walking, metadata extraction, and deleted-file
  recovery.
- **Platform:** Linux (CLI). Python, following modern best practices (PEP 8,
  type hints, src layout, pytest).
- **Why automation:** Manual Autopsy GUI analysis is slow and inconsistent;
  PyAutopsy aims for a repeatable, scriptable pipeline that produces consistent
  reports.
- **Evidence integrity matters:** Forensic soundness (read-only handling of
  evidence, hashing, reproducibility) is a first-class concern, not an add-on.
- **Shipped state (v1.0, 2026-06-01):** ~11,550 LOC src + ~7,230 LOC tests
  (Python 3.11+, src layout). Stack: pytsk3 + pyewf (E01), python-magic, Typer +
  Rich, Jinja2, stdlib hashlib/sqlite3/re/gzip/zoneinfo — **no plaso/dfVFS/ssdeep
  yet** (deferred). Two native seams only (`evidence/image.py`,
  `evidence/filesystem.py`); `CaseStore` is the sole DB writer. CLI surface:
  `ingest | walk | analyze | recover | search | logs`. Known tech debt + Nyquist
  coverage gaps recorded in `milestones/v1.0-MILESTONE-AUDIT.md`.

## Constraints

- **Tech stack**: Python on Linux — Required: project explicitly targets Python + Linux
- **Dependencies**: Autopsy / The Sleuth Kit (TSK) and Python bindings (e.g. `pytsk3`) — Required: core forensic primitives come from TSK, not reimplemented
- **Forensic soundness**: Evidence sources must be treated read-only; findings must be hashable/reproducible — Why: output supports evidence presentation
- **Reporting**: Report must be both human-readable and structured/exportable — Why: needs to serve both investigators and downstream tooling

## Key Decisions

<!-- Decisions that constrain future work. -->

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Wrap The Sleuth Kit via `pytsk3` directly (not the Autopsy GUI/Jython modules) rather than reimplement forensic primitives | TSK is the mature, court-trusted standard; pytsk3 gives native Python access without a GUI runtime | ✓ Good — single-native-seam discipline held across all 5 phases; recovery/walk/search all ride the seam |
| Python + Linux CLI as the delivery surface (Typer) | Matches stated requirements; scriptable and automatable | ✓ Good — 6 subcommands ship; `analyze` composes the whole pipeline in one process |
| Treat evidence read-only with hashing/chain-of-custody metadata | Output supports evidence presentation; forensic soundness required | ✓ Good — read-only never-mounted guard (before+after open) in every orchestrator; end-of-run re-verify; CaseStore sole writer; append-only audit log |
| Report is both human-readable (HTML) and structured (JSON) | Serves evidence presentation and machine consumption | ✓ Good — byte-identical reproducible bodies; run metadata segregated to sidecar (CLI-02). PDF rendering deferred (WeasyPrint not adopted in v1.0) |
| Honesty over verdicts — surface observed facts + confidence tiers + tamperability/completeness findings, never inferred intent | Forensic reports must be neutral; overclaiming invites bias challenges | ✓ Good — recovery confidence tiers, neutral "known" framing, D-44 tamperability caveat all verbatim-neutral; verified for accusatory vocabulary (none) |
| Single shared `timeline_events` model + total-order read = the super-timeline | Avoids a second ordering path; fs and log events merge for free | ✓ Good — TIME-02 needed no new ordering code; surrogate-`id` tiebreak (CR-01) keeps tied/NULL-key log events deterministic |
| Defer plaso/dfVFS/journald/carving to v2; stdlib-only log+search in v1.0 | Smallest install surface; fastest defensible "image → report" path | ✓ Good — zero new runtime dep added across Phase 5 (D-43 guard) |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-06-01 after v1.0 MVP milestone — all 5 phases shipped (27/27 v1 requirements validated); the full image (+ logs) → defensible report pipeline is complete behind one `pyautopsy analyze` command. Next milestone scope via `/gsd-new-milestone`.*
