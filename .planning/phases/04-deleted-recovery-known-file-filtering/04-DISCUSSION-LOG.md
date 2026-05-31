# Phase 4: Deleted Recovery & Known-File Filtering - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-31
**Phase:** 4-Deleted Recovery & Known-File Filtering
**Areas discussed:** Recovery scope & tiers, Recovered-bytes output, Known-file filtering input, Pipeline & CLI integration

---

## Recovery scope & confidence tiers

| Option | Description | Selected |
|--------|-------------|----------|
| Metadata-intact + overwrite | TSK `icat` recovery on deleted inodes where meta+data survive; overwrite detection via block-reallocation; tiers intact vs partial/overwritten; defer ext4-journal + carving | ✓ |
| + ext4 journal recovery | Also mine ext4 jbd2 journal, adds a `journal` tier (fragile, ext-only) | |
| + signature carving | Full taxonomy incl. photorec/scalpel carving — pulls CARVE-01 forward | |

**User's choice:** Metadata-intact + overwrite
**Notes:** Smallest defensible MVP, matches RECOV-01..03 exactly. Carving (CARVE-01) and ext4-journal explicitly deferred; tier taxonomy left forward-shaped (D-29/D-30/D-31).

---

## Recovered-bytes output

| Option | Description | Selected |
|--------|-------------|----------|
| Write to recovered/ + catalog | Extract recovered bytes into case-dir `recovered/` via safe_extract jail, deterministic name by volume+inode, catalog as files rows, hash written bytes | ✓ |
| Catalog-only, in-memory hash | Hash in memory, record rows, write no bytes (lower disk, examiner can't open content) | |
| Configurable (default write) | Write by default, `--no-extract` for catalog-only | |

**User's choice:** Write to recovered/ + catalog
**Notes:** Forensic inspectability prioritized; routed through existing confinement jail; reuses Phase 2 single-pass hashing (D-33/D-34/D-35).

---

## Known-file filtering input

| Option | Description | Selected |
|--------|-------------|----------|
| NSRL SQLite + custom lists | User-supplied NSRL RDS minimal SQLite (stdlib sqlite3) + custom allow/block hash lists; match MD5/SHA-1→SHA-256; neutral "known" annotation | ✓ |
| Custom lists only (defer NSRL) | Custom allow/block lists only this phase; defer NSRL ingestion | |
| You decide | Pick most forensically-sound default | |

**User's choice:** NSRL SQLite + custom lists
**Notes:** NSRL not bundled (large external dataset, examiner-supplied). Match on already-computed MD5/SHA-1 then SHA-256. Surfaced as neutral "known" (noise reduction), never good/bad (D-36/D-37/D-38/D-39).

---

## Pipeline & CLI integration

| Option | Description | Selected |
|--------|-------------|----------|
| Standalone + opt-in in analyze | New `pyautopsy recover` subcommand + `--nsrl`/`--hash-set` flags; analyze runs recovery/filter only when inputs supplied — keeps Phase 3 report baseline stable | ✓ |
| Always in analyze | analyze always recovers + filters (richer default, heavier run, changes baseline) | |
| Standalone only | Separate subcommands, never in analyze (MVP report won't show recovered/known) | |

**User's choice:** Standalone + opt-in in analyze
**Notes:** Recovery is an explicit examiner choice; default `analyze` stays byte-deterministic per CLI-02. New report sections obey determinism + total-order contracts (D-40/D-41/D-42).

---

## Claude's Discretion

- Exact `recovered/` naming/sanitization scheme and the column-vs-`attributes` split for recovery metadata + known-match annotations — finalized by the planner against the existing schema (sole-writer + CLI-02 preserved).
- Orphan reporting shape (flag + section vs derived view), provided orphans are reported separately (RECOV-02).

## Deferred Ideas

- Signature/file carving (CARVE-01) — own later effort, new tool deps.
- ext4 journal (jbd2) recovery + `journal` tier — deferred (fragile, ext-only).
- exFAT/HFS+/APFS deleted-file recovery (RECOV-04) — gated on TSK build.
- Config-recipe runs (CONF-01) and IOC/known-bad content search + offsets (SEARCH-02) — Phase 5.
- Fuzzy-hash (ssdeep/TLSH) near-duplicate matching — similarity not integrity; out of FILTER-01 scope.
