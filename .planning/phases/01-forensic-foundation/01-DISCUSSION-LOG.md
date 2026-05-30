# Phase 1: Forensic Foundation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-30
**Phase:** 1-Forensic Foundation
**Mode:** --auto (recommended option auto-selected per area; no interactive prompts)
**Areas discussed:** Case store layout, Image adapter & read-only handling, Hashing strategy, Audit log format, Safe-extraction jail, CLI surface

---

## Case Store & Layout

| Option | Description | Selected |
|--------|-------------|----------|
| SQLite case DB in dedicated case dir (typed cols + JSON attributes) | One `case.db` + `logs/`/`exports/`; matches Autopsy/plaso | ✓ |
| Flat files (JSON/CSV per artifact) | Simpler but no transactions, weak for chain-of-custody | |
| Embedded document store | Overkill, extra dependency | |

**Choice:** SQLite case DB with typed-core-columns + JSON `attributes` schema.
**Notes:** Both reference tools (Autopsy, plaso) validate SQLite; single hashable/archivable file aids chain of custody. (ARCHITECTURE.md)

---

## Image Adapter & Read-Only Handling

| Option | Description | Selected |
|--------|-------------|----------|
| pytsk3 + pyewf Img_Info adapter, O_RDONLY, never mount | raw/dd direct; E01 via pyewf as optional `[ewf]` extra | ✓ |
| Loop-mount the image and walk the FS | Modifies evidence (journal replay, atimes) — forensically unsound | |
| Embed Autopsy app | Jython 2.7 can't load native libs; no headless CLI | |

**Choice:** pytsk3 byte-layer read-only; pyewf adapter for E01.
**Notes:** Never mount the source (PITFALLS P1). Isolate native calls behind one seam.

---

## Hashing Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Single streaming pass computing MD5+SHA-256 | One read; compare to acquisition hash; re-verify at end | ✓ |
| Separate pass per algorithm | Doubles I/O on large images | |
| SHA-256 only | Loses MD5 hash-set interop | |

**Choice:** Single-pass MD5+SHA-256, re-verify at end, fail loudly on mismatch.
**Notes:** SHA-256 primary; MD5 for legacy hash sets.

---

## Audit Log Format

| Option | Description | Selected |
|--------|-------------|----------|
| Append-only JSON Lines (`logs/audit.jsonl`) | One structured UTC event per line, in case dir only | ✓ |
| Plain text log | Human-readable but hard to parse | |
| SQLite table only | Less portable as a standalone audit artifact | |

**Choice:** JSONL append-only in the case directory.
**Notes:** UTC ISO-8601 timestamps from phase 1 (PITFALLS P4). Optional DB mirror left to discretion.

---

## Safe-Extraction Jail

| Option | Description | Selected |
|--------|-------------|----------|
| Dedicated `safe_extract` with path-confine + symlink refusal + bomb limits | Phase gate, validated on malicious-archive fixture | ✓ |
| Stdlib `extractall()` | Zip Slip + decompression-bomb vulnerable | |
| Extract then validate | Damage already done by the time you check | |

**Choice:** Hardened `safe_extract` utility as the only sanctioned extraction path.
**Notes:** Reject Zip Slip / symlink escape; enforce max size/ratio/depth/count (PITFALLS P6/P12).

---

## CLI Surface

| Option | Description | Selected |
|--------|-------------|----------|
| Typer — `pyautopsy ingest <image> --case ... --examiner ... --evidence-id ... [--acquisition-hash]` | Modern typed CLI; pairs with src layout | ✓ |
| argparse | Stdlib but more boilerplate | |
| click | Capable but Typer is the lighter modern choice | |

**Choice:** Typer; `pyautopsy ingest` command in phase 1, full `analyze` pipeline in Phase 3.

---

## Claude's Discretion

- Exact SQLite table/column and module/file names (consistent with the schema decision).
- Streaming hash chunk size and exact decompression-bomb thresholds (sane configurable defaults).
- Whether to mirror the JSONL audit log into a SQLite table as well.

## Deferred Ideas

- Filesystem walk / MACB metadata / per-file hashing → Phase 2
- Deleted recovery, orphans, NSRL/custom hash filtering → Phase 4
- Log parsing, shared event model, super-timeline, search → Phase 5
- Timeline + human/JSON report, single-command `analyze` → Phase 3
- Carving, journald/auditd/wtmp, YARA, CASE/UCO, config recipes, plaso backend → v2
