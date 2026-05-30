# PyAutopsy

## What This Is

PyAutopsy is a Python tool for automated digital forensic analysis on Linux. It
ingests disk images and log files, analyzes file metadata, recovers deleted
files, and generates a structured forensic report suitable for evidence
presentation. It is built on top of Autopsy / The Sleuth Kit, wrapping their
forensic primitives in an automated, scriptable Python workflow.

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

### Active

<!-- Current scope. Building toward these. Hypotheses until shipped. -->

- [ ] Analyze file metadata (timestamps, ownership, permissions, sizes, MAC times) — Phase 2
- [ ] Recover deleted files from supported filesystems — Phase 4
- [ ] Parse and analyze log files for forensically relevant events — Phase 5
- [ ] Build a timeline of file/system activity from metadata and logs — Phases 3 & 5
- [ ] Generate a forensic report suitable for evidence presentation (human-readable + structured) — Phase 3

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

## Constraints

- **Tech stack**: Python on Linux — Required: project explicitly targets Python + Linux
- **Dependencies**: Autopsy / The Sleuth Kit (TSK) and Python bindings (e.g. `pytsk3`) — Required: core forensic primitives come from TSK, not reimplemented
- **Forensic soundness**: Evidence sources must be treated read-only; findings must be hashable/reproducible — Why: output supports evidence presentation
- **Reporting**: Report must be both human-readable and structured/exportable — Why: needs to serve both investigators and downstream tooling

## Key Decisions

<!-- Decisions that constrain future work. -->

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Build on Autopsy / The Sleuth Kit rather than reimplement forensic primitives | TSK is the mature, trusted standard for filesystem forensics and deleted-file recovery | — Pending |
| Python + Linux CLI as the delivery surface | Matches stated requirements; scriptable and automatable | — Pending |
| Treat evidence read-only with hashing/chain-of-custody metadata | Output supports evidence presentation; forensic soundness required | — Pending |
| Report is both human-readable and structured (e.g. HTML/PDF + JSON) | Serves evidence presentation and machine consumption | — Pending |

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
*Last updated: 2026-05-30 after Phase 1 (Forensic Foundation) completion*
