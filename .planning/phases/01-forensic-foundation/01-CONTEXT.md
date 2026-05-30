# Phase 1: Forensic Foundation - Context

**Gathered:** 2026-05-30
**Status:** Ready for planning

<domain>
## Phase Boundary

This phase delivers the **forensic-soundness spine** that every later analysis
phase writes into. In scope:

- Read-only ingest of a disk image (raw/dd and E01/EWF) — never mounted (INGEST-01, INGEST-03)
- Source integrity: compute MD5 + SHA-256, compare to a supplied acquisition hash when provided, re-verify at end of run, fail loudly on mismatch (INGEST-02)
- A persistent **case store** (SQLite) + case directory holding all output, separate from the read-only evidence (foundation for everything)
- Case / chain-of-custody metadata recorded in the case store (REPORT-01)
- An append-only **audit log** of tool actions written only to the case directory (REPORT-02)
- A hardened **safe-extraction** utility rejecting Zip Slip, symlink escape, and decompression bombs (INGEST-04)
- The `pyautopsy ingest` command that ties these together (partial CLI; full pipeline command lands in Phase 3)

Out of scope for this phase (later phases): filesystem walk / metadata (Phase 2),
deleted recovery & filtering (Phase 4), log parsing / timeline / search (Phase 5),
report rendering (Phase 3). This phase establishes the substrate they depend on.

</domain>

<decisions>
## Implementation Decisions

*Auto-mode discussion: each gray area resolved to the research-backed recommended
option. Rationale traces to `.planning/research/{STACK,ARCHITECTURE,PITFALLS}.md`.*

### Case Store & Layout
- **D-01:** The case is a **directory** created by the tool, containing a single **SQLite database** (`case.db`) plus subdirectories `logs/` (audit log), `exports/` (recovered files / reports in later phases), and metadata. The read-only evidence image is **never** placed inside or modified.
- **D-02:** SQLite schema follows the research pattern: **typed core columns + a JSON `attributes` column** so heterogeneous later producers (metadata, log events, findings) never force a migration. Phase 1 creates the schema and the `case`/chain-of-custody and `audit`/evidence tables; later phases add rows/tables.
- **D-03:** SQLite is the case store (both Autopsy and plaso validate this choice): single-file, archivable, hashable for chain of custody, transactional, queryable.

### Image Adapter & Read-Only Handling
- **D-04:** Use **pytsk3** (`Img_Info`) to open raw/dd images directly. For **E01/EWF**, wrap **pyewf** as a `pytsk3.Img_Info` subclass adapter. pyewf ships as an optional `[ewf]` install extra so the core install stays light.
- **D-05:** Evidence is opened **`O_RDONLY` at the byte layer via TSK** — the source is **never mounted** (mounting replays journals, bumps mount counts, updates atimes — see PITFALLS P1). A hard guard forbids any write path to the source.
- **D-06:** Isolate all native `pytsk3`/`pyewf` calls behind one module seam (e.g. `evidence/image.py`) so the rest of the system is testable without an image and the native dependency is swappable.

### Hashing & Integrity
- **D-07:** Compute **MD5 + SHA-256 in a single streaming pass** over the image (configurable chunk size), not two passes. SHA-256 is the forensic primary; MD5 retained for legacy hash-set interop.
- **D-08:** If the user supplies an acquisition hash, compare and record PASS/FAIL. **Re-verify the source hash at end of run**; any mismatch is a loud, non-zero-exit failure recorded in the audit log.

### Audit Log
- **D-09:** Append-only **JSON Lines** file (`logs/audit.jsonl`) — one structured event per line (timestamp UTC, action, inputs, hashes, parameters, tool+TSK versions, outcome, errors). Machine-readable and append-friendly; written **only** to the case directory, never near the evidence.
- **D-10:** All timestamps are **UTC, timezone-aware ISO-8601** from the very first phase (PITFALLS P4 — UTC-everywhere must not be retrofitted).

### Safe-Extraction Jail
- **D-11:** A dedicated `safe_extract` utility is the only sanctioned way to expand any archive/container. It **canonicalizes and confines** every member path to the destination (reject path traversal / Zip Slip), **refuses symlinks and special files**, and enforces hard limits: max total uncompressed size, max compression ratio, max nesting depth, max entry count (reject decompression bombs). This is a **phase-completion gate**, validated against a malicious-archive fixture (PITFALLS P6/P12).

### CLI Surface
- **D-12:** Use **Typer** for the CLI. Phase 1 ships `pyautopsy ingest <image> --case <case-dir> --examiner <name> --evidence-id <id> [--acquisition-hash <hash>]`. The single-command full pipeline (`pyautopsy analyze ...`) is assembled in Phase 3 on top of these primitives.

### Project Scaffolding
- **D-13:** Standard modern-Python layout: **src layout**, `pyproject.toml` with **hatchling** backend, **pytest** (with `tmp_path` fixtures for evidence/case dirs), **ruff** + **mypy**. Pin the dated TSK/pyewf releases for reproducibility. Document native system deps (`sleuthkit`/`libtsk`, `libewf`) in README; provide a Containerfile.

### Claude's Discretion
- Exact SQLite table/column names and module/file names — planner/executor decide, consistent with D-02.
- Chunk size for streaming hashing, exact bomb-limit thresholds — pick sane defaults, make configurable.
- Whether the audit log is *also* mirrored into a SQLite table in addition to JSONL.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project specs
- `.planning/PROJECT.md` — product definition, core value, constraints (forensic soundness, read-only, Linux CLI)
- `.planning/REQUIREMENTS.md` — Phase 1 maps INGEST-01..04, REPORT-01, REPORT-02
- `.planning/ROADMAP.md` §"Phase 1: Forensic Foundation" — goal + 5 success criteria (the acceptance bar)

### Research (drives the decisions above)
- `.planning/research/STACK.md` — pytsk3-vs-Autopsy decision, pyewf adapter, native deps, version pinning, packaging
- `.planning/research/ARCHITECTURE.md` — Acquire→Process→Analyze→Report pipeline, SQLite case store, typed-columns+JSON-attributes schema, `pytsk3` single-seam isolation, read-only evidence handling
- `.planning/research/PITFALLS.md` — P1 (never mount source), P4 (UTC-everywhere), P6/P12 (Zip Slip / decompression bombs), reproducibility/defensibility
- `.planning/research/SUMMARY.md` — cross-cutting synthesis and phase ordering

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- None yet — greenfield. Repo contains only `.gitignore` and `LICENSE`. This phase establishes the project skeleton (src layout, pyproject, case store, evidence seam) that all later phases extend.

### Established Patterns
- None yet. Patterns set here (single native seam, SQLite case store, UTC-everywhere, append-only audit, src layout) become the conventions later phases must follow.

### Integration Points
- The SQLite case store schema and the forensic-event/attributes model defined here are the integration surface every later phase writes into (metadata rows, log events, findings).

</code_context>

<specifics>
## Specific Ideas

- Tool is "PyAutopsy" but does **not** embed Autopsy-the-application — it drives The Sleuth Kit directly via pytsk3 (STACK.md decision). The name is the product, not an instruction to wrap the Autopsy GUI/Jython.
- Forensic soundness is a first-class, non-negotiable property of this phase — a tool that can modify evidence is unusable regardless of features.

</specifics>

<deferred>
## Deferred Ideas

- Filesystem walk, MACB metadata, per-file hashing → **Phase 2**
- Deleted-file recovery, orphans, NSRL/custom hash filtering → **Phase 4**
- Log parsing, shared event model, super-timeline, keyword/IOC search → **Phase 5**
- Timeline + human/JSON report rendering, single-command `analyze` pipeline → **Phase 3**
- File carving, journald/auditd/wtmp parsers, YARA, CASE/UCO export, config-driven recipes, plaso backend → **v2** (see REQUIREMENTS.md v2)

</deferred>

---

*Phase: 1-Forensic Foundation*
*Context gathered: 2026-05-30*
