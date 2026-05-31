# Phase 4: Deleted Recovery & Known-File Filtering - Research

**Researched:** 2026-05-31
**Domain:** TSK deleted-file recovery (pytsk3), filesystem allocation analysis, NSRL/hash-set known-file filtering
**Confidence:** HIGH (recovery + overwrite mechanism empirically verified against installed pytsk3 20260520 on the committed ext4/NTFS fixtures; NSRL schema CITED from NIST/community sources)

## Summary

This phase layers two opt-in forensic capabilities onto the proven Phase 1-3 SQLite spine: (1) metadata-intact recovery of deleted/orphan file **contents** with honest confidence labeling, and (2) known-file filtering against NSRL RDS + custom hash sets. Both are reads-only over the existing `evidence/filesystem.py` native seam and writes-only through `CaseStore` — no new native dependency and no new third-party package (NSRL is queried with stdlib `sqlite3`).

The recovery mechanism is **verified working** against the installed `pytsk3 20260520`: `FS_Info.open_meta(inode=<meta_addr>)` reopens a deleted inode by address, and `File.read_random(0, size)` returns its surviving bytes (confirmed: deleted ext4 inode 13 round-tripped its exact 22 content bytes; NTFS resident `$DATA` recovers from the MFT record). The confidence-tier (`intact` vs `partial/overwritten`) discriminator is built by enumerating the deleted inode's data-block runs (iterating `File` attributes → their `TSK_FS_ATTR_RUN` linked list, both verified iterable in pytsk3) and testing whether any of those blocks now belong to an **allocated** file. Critically, pytsk3 **does not expose the filesystem allocation bitmap directly** (`TSK_FS_BLOCK` is not usable from Python and there is no `block_walk` binding), so the allocated-block set must be **derived** by walking every allocated inode's runs once — a verified-working approach.

**Primary recommendation:** Implement two thin vertical slices behind the existing seam. Slice A (recovery): add `evidence/filesystem.py` functions `recover_meta(fs, inode)` (returns a pytsk3-free `RecoveredEntry` value object with a `read_random` closure + its block-run list) and `allocated_data_blocks(fs)` (the derived bitmap), then an orchestrator `core/recover.py` that hashes recovered bytes via the existing `integrity.hash_file`, classifies the tier, writes bytes through `safe_extract`-style confinement, and catalogs recovered `files` rows. Slice B (filtering): a stdlib-`sqlite3` NSRL membership checker + a custom-list parser, run as a post-walk pass writing neutral "known" annotations via `CaseStore`. Keep both out of the default `analyze` path unless `--nsrl`/`--hash-set`/recover inputs are supplied (D-40), preserving the Phase-3 byte-stable report baseline.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-29:** Phase 4 ships **metadata-intact recovery only** — recover deleted entries whose meta slot + data block runs survive, via the existing `evidence/filesystem.py` native seam (TSK `File`/`read_random`, the `icat` equivalent). No new native dependency. ext4-journal recovery and signature carving are explicitly **deferred** (carving = CARVE-01).
- **D-30:** Confidence taxonomy is **two tiers this phase**: `intact` (all data blocks still unallocated / not reused) and `partial/overwritten` (one or more data blocks have been reallocated to another file or are no longer allocated to this inode). The tier string field is designed so a future `journal` / `carved` tier can be added as a new value with **no schema churn**.
- **D-31:** **Overwrite detection** compares the recovered inode's data block runs against the filesystem allocation state (and/or blocks now owned by other allocated files). Any reallocated/no-longer-owned block ⇒ `partial/overwritten`. Per-filesystem caveats (e.g. FAT cluster reuse, NTFS resident vs non-resident) are recorded as part of the tier rationale, not hardcoded as certainty.
- **D-32 (honesty, RECOV-03):** Confidence labels describe **data survival**, never user intent. The tool must **never** assert "the user deleted this." Tier copy and report wording are reviewed for overclaiming (mirrors Phase 3 WR-02).
- **D-33:** Recovered file **contents are written to disk** under a case-dir `recovered/` tree, routed through the existing `util/safe_extract` confinement jail (realpath confinement + bomb caps), AND cataloged as `files` rows. Hashes (MD5/SHA-1/SHA-256) are computed from the **written bytes** (reuse the Phase 2 single-pass hashing path).
- **D-34:** Recovered-file on-disk naming is **deterministic** and collision-safe, keyed by volume + inode (e.g. `recovered/vol<volume_id>-off<volume_offset>/<meta_addr>-<sanitized_name>`). Deterministic naming preserves CLI-02 reproducibility and avoids name collisions between distinct deleted entries that reclaimed the same path. (Exact scheme finalized in planning.)
- **D-35:** Recovered `files` rows reuse the **existing `files` schema** (`allocated`, `meta_addr`, `volume_id/offset`, hash + MACB columns already present from Phase 2). Recovery-specific metadata (confidence tier, recovered path, overwrite evidence) lives in the row's `attributes` JSON and/or a narrow new column set — **CaseStore remains the sole writer** (no raw SQL outside `store.py`). Final column-vs-attributes split decided in planning.
- **D-36:** Filtering accepts **two input kinds**: (1) a user-supplied **NSRL RDS "minimal" SQLite** database, queried directly with stdlib `sqlite3` (no new dep, read-only); (2) **custom allow/block hash lists** (newline-delimited hashes, MD5/SHA-1/SHA-256 auto-detected by hex length). NSRL is **not bundled** — it is a large external dataset the examiner provides.
- **D-37:** Match key order is **MD5 / SHA-1 first** (NSRL RDS is keyed on those), falling back to **SHA-256**. We already compute all three per file (Phase 2), so no re-hashing is needed for allocated files.
- **D-38 (FILTER-01 neutrality):** A match is surfaced as a neutral **"known"** annotation carrying `source` (nsrl | custom) and the **list/set name**, plus allow/block classification for custom lists — **never** a good/bad verdict. The report uses "known" framing as **noise reduction**, not adjudication.
- **D-39:** Filtering is a **post-walk pass over `files` rows** (allocated and recovered), writing match annotations via CaseStore. Storage shape (annotation column(s) on `files` vs a dedicated `known_file_matches` table) decided in planning; whichever preserves determinism and the sole-writer rule.
- **D-40:** New standalone **`pyautopsy recover`** subcommand; filtering exposed as flags (e.g. `--nsrl <db>`, `--hash-set <list>` with allow/block sense). The **D-21 `analyze` pipeline runs recovery/filtering only when the relevant inputs are supplied** — default `analyze` keeps the Phase 3 deterministic report baseline byte-stable. Recovery is an explicit examiner choice, not an implicit default.
- **D-41 (determinism, CLI-02):** Recovered-file lists and "known" annotations in the report body are ordered by the **existing total order** (`store.get_*` ORDER BY — `ts→volume→offset→path→...→id`), and the report body stays free of wall-clock/run metadata. New report sections (recovered files, orphans, known-file summary) must be byte-deterministic across identical runs.
- **D-42 (read-only):** All recovery reads go through the `filesystem.py` seam; the evidence source is **never** written. Only the case directory (`recovered/`, `case.db`, reports) is written. Read-only re-verify (Phase 1) still runs end-of-run.

### Claude's Discretion

- Exact `recovered/` naming/sanitization scheme and the column-vs-`attributes` split for recovery metadata and known-match annotations (D-34/D-35/D-39) — to be finalized by the planner against the existing schema, preserving the CaseStore-sole-writer rule and CLI-02 determinism.
- Whether orphan reporting is a boolean flag + report section or a small derived view — planner's call, provided orphans are reported **separately** (RECOV-02).

### Deferred Ideas (OUT OF SCOPE)

- **Signature/file carving** of unallocated space (photorec/scalpel/foremost) — **CARVE-01**, its own later effort; brings new external tool deps.
- **ext4 journal (jbd2) recovery** + a `journal` confidence tier — deferred; fragile and ext-only. Taxonomy leaves room for it.
- **exFAT/HFS+/APFS deleted-file recovery** — **RECOV-04**, gated on the linked TSK build / runtime capability probe.
- **Config-recipe runs (CONF-01)** and **IOC / known-bad content search + offsets (SEARCH-02)** — Phase 5 territory.
- Fuzzy-hash (ssdeep/TLSH) near-duplicate matching — similarity, not integrity; not part of FILTER-01's known-file filtering.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| RECOV-01 | Enumerate and recover deleted files where metadata/data remain intact | `FS_Info.open_meta(inode=meta_addr)` + `File.read_random` verified working (ext4 inode 13, NTFS resident $DATA). Recover via the seam; hash written bytes with `integrity.hash_file`; catalog as `files` rows with `allocated=False` + recovery metadata. (§Code Examples 1-3) |
| RECOV-02 | Report orphan files (deleted, parent dir gone) separately | Two discriminators verified: TSK `$OrphanFiles` virtual directory + the per-inode `TSK_FS_META_FLAG_ORPHAN` meta flag. Phase 2 already records `parent_addr`/`meta_addr`; orphans are deleted entries reached via `$OrphanFiles` / lacking a surviving parent. (§Pattern 3) |
| RECOV-03 | Label each recovered file with a confidence level (intact vs partial/overwritten) | Block-run enumeration (`File` attrs → `TSK_FS_ATTR_RUN` runs) vs a derived allocated-block set; intersection ⇒ `partial/overwritten`, else `intact`. Verified: deleted inode 13's block {25} has zero overlap with the 22 allocated data blocks ⇒ `intact`. (§Pattern 2, §Code Example 4) |
| FILTER-01 | Filter files against NSRL RDS + custom hash sets, surfacing matches as "known" | NSRL RDSv3 "minimal" is a SQLite DB with a `FILE` table (md5/sha1/sha256 columns); query read-only via stdlib `sqlite3`. Custom lists are newline hashes, algorithm inferred by hex length. Match key order md5→sha1→sha256 per D-37; emit neutral `known` annotation per D-38. (§Pattern 4-5, §Code Example 5-6) |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Reopen deleted inode by address + read its bytes | Native seam (`evidence/filesystem.py`) | — | D-14 allowlist: only `image.py`/`filesystem.py` may import pytsk3. `open_meta`/`read_random` are TSK File-layer calls and MUST live here. |
| Enumerate deleted inode's data-block runs | Native seam (`evidence/filesystem.py`) | — | Touches `pytsk3.Attribute`/`TSK_FS_ATTR_RUN`. Runs must be returned as plain ints (no native type escapes the seam). |
| Derive allocated-block set (the bitmap) | Native seam (`evidence/filesystem.py`) | — | Requires iterating every allocated inode via `open_meta`; pure pytsk3. Return a `frozenset[int]` of block addrs. |
| Orphan discrimination (`$OrphanFiles` / ORPHAN flag) | Native seam (`evidence/filesystem.py`) | Orchestrator (`core/recover.py`) | Reading the meta flag / orphan dir is seam work; deciding "report separately" is orchestrator policy. |
| Confidence-tier classification | Orchestrator (`core/recover.py`) | — | Pure logic over the seam's plain-int run lists + allocated set. No pytsk3 — testable with fakes. |
| Hash recovered bytes + content-type | Orchestrator (`core/recover.py`) | Existing `integrity.hash_file` / `filetype` | Reuse the Phase-2 single-pass hashing path on the seam's `read_random` closure. |
| Write recovered bytes to `recovered/` tree | Orchestrator → `util/safe_extract` confinement | — | Confined, deterministic naming (D-33/D-34). Source is never written (D-42). |
| Catalog recovered `files` rows + recovery metadata | `CaseStore` (`case/store.py`) | — | Sole-writer rule (D-08/D-35). New store method(s); no raw SQL elsewhere. |
| NSRL membership query | New `filter`/`knownfiles` module (stdlib `sqlite3`) | — | Read-only attach to examiner-supplied DB; NOT a native seam (sqlite3 is stdlib, no pytsk3) so D-14 unaffected. |
| Custom hash-set parsing + allow/block model | New `filter`/`knownfiles` module | — | Pure stdlib text parsing. |
| Known-match annotation persistence | `CaseStore` (`case/store.py`) | — | Post-walk pass; sole-writer rule (D-39). |
| Recovered/orphan/known report sections | `report/assemble.py` (+ HTML template, JSON) | — | Extend the deterministic body; D-26 total order; no wall-clock (D-41). |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `pytsk3` | 20260520 (installed, pinned in pyproject) | Reopen deleted inodes (`open_meta`), read content (`read_random`), enumerate attributes/runs | Already the project's filesystem seam; the `icat` + run-enumeration equivalents are all present and verified. [VERIFIED: installed `pytsk3.get_version()` == `20260520`; API exercised live] |
| `sqlite3` | stdlib (Python 3.14) | Read-only membership query against the examiner-supplied NSRL RDS DB; also the case store | No new dependency (D-36). NSRL RDSv3 is distributed only as SQLite. [VERIFIED: stdlib] |
| `hashlib` (via existing `integrity.hash_file`) | stdlib | Hash recovered bytes (MD5/SHA-1/SHA-256) | Reuse the Phase-2 single-pass path (D-33/D-37). [VERIFIED: codebase `walk.py` / `integrity`] |

### Supporting (all already in-tree — reused, not added)

| Library / Module | Purpose | When to Use |
|------------------|---------|-------------|
| `evidence/filesystem.py` | The ONLY recovery-read seam (extend with recover/run/bitmap functions) | All pytsk3 access (D-14) |
| `util/safe_extract.py` (`_confined_target`, `_sanitize_name`, realpath confinement) | Confine + sanitize recovered-file writes under `recovered/` | Writing recovered bytes (D-33/D-34) |
| `evidence/integrity.py` (`hash_file`) | Single-pass MD5/SHA-1/SHA-256 over a `read_random` closure | Hashing recovered bytes |
| `evidence/filetype.py` (`file_type`) | Content-signature typing (head bytes only) | Typing recovered bytes (optional, mirrors walk) |
| `case/store.py` + `schema.sql` | Sole DB writer; `files` table reuse + new recovery/known storage | All persistence (D-08/D-35/D-39) |
| `report/assemble.py` + `htmlreport.py` + `jsonreport.py` | Deterministic body + renderers | New recovered/orphan/known sections (D-41) |
| `typer` | CLI | New `recover` command + `--nsrl`/`--hash-set` flags (D-40) |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `open_meta` + `read_random` in-process | shelling out to TSK `icat` | Brittle text/exit-code parsing, a second process, and it bypasses the D-14 seam. Project mandates wrapping pytsk3 (CLAUDE.md "What NOT to Use"). Rejected. |
| Derived allocated-block set (walk every allocated inode's runs) | direct allocation-bitmap read (`TSK_FS_BLOCK` / `block_walk`) | **pytsk3 exposes NO usable block-bitmap API** — `TSK_FS_BLOCK()` constructs but immediately invalidates, and there is no `block_walk` binding (verified). The derived approach is the only pytsk3-native option. (§Pitfall 1) |
| stdlib `sqlite3` for NSRL | a dedicated NSRL library / preloading all hashes into a Python set | D-36 locks stdlib `sqlite3`, read-only. Preloading millions of rows into a set blows memory; an indexed SQL lookup is the scalable choice. (§Pattern 4) |

**Installation:** No new packages. All recovery + filtering uses the existing pinned `pytsk3==20260520` and Python stdlib. `pyproject.toml [project.dependencies]` is unchanged.

**Version verification:**
```bash
python -c "import pytsk3; print(pytsk3.get_version())"   # -> 20260520  [VERIFIED]
python -c "import sqlite3, sys; print(sqlite3.sqlite_version, sys.version)"  # stdlib  [VERIFIED]
```

## Package Legitimacy Audit

> This phase installs **no external packages** — recovery uses the already-pinned `pytsk3==20260520` (added and audited in Phase 2) and filtering uses Python stdlib `sqlite3`/`hashlib` only (D-36). There is nothing new to slopcheck.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| (none — no new dependency) | — | — | — | — | — | N/A |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

`pytsk3==20260520` legitimacy was established in Phase 2 (maintained by Joachim Metz / libyal, Apache-2.0, used by plaso/dfVFS) and is already pinned and installed; this phase adds no install step.

## Architecture Patterns

### System Architecture Diagram

```
                          pyautopsy recover <image> --case <dir>
                          pyautopsy analyze ... [--recover] [--nsrl DB] [--hash-set L]
                                          │
                                          ▼
                          ┌───────────────────────────────────────┐
                          │  core/recover.py  (orchestrator,        │
                          │  imports NO pytsk3 — D-14)              │
                          └───────────────────────────────────────┘
                                          │
        ┌─────────────────────────────────┼──────────────────────────────────┐
        ▼ (read-only, seam)               ▼ (sole writer)                     ▼ (post-walk)
┌────────────────────────┐   ┌──────────────────────────┐      ┌─────────────────────────────┐
│ evidence/filesystem.py │   │ case/store.py (CaseStore) │      │ filter/knownfiles.py        │
│  NATIVE SEAM (pytsk3)  │   │  files rows + recovery    │      │  stdlib sqlite3 + list parse │
│                        │   │  metadata + known matches │      │  (NOT a native seam)         │
│ recover_meta(fs,inode) │   └──────────────────────────┘      └─────────────────────────────┘
│   → RecoveredEntry      │              ▲                                   │
│   (read_random closure, │              │                                   │
│    block-run list,      │   ┌──────────┴───────────┐         examiner-supplied
│    meta flags)          │   │ util/safe_extract     │         NSRL .db  +  custom
│ allocated_data_blocks() │   │ confinement → write   │         allow/block hash lists
│   → frozenset[int]      │   │ recovered/ tree (D-33)│
│ open_dir($OrphanFiles)  │   └───────────────────────┘
└────────────────────────┘
        │
        ▼ read-only bytes (never writes source — D-42)
   evidence image (raw / E01, opened read-only via image.py seam)

                                          │
                                          ▼
                   report/assemble.py (deterministic body, D-26 order, no wall-clock)
                   + htmlreport.py / jsonreport.py
                   → new sections: "Recovered Files", "Orphan Files",
                                   "Known-File Filtering (noise reduction)"
```

Data flow (recovery slice): image → seam reopens each deleted inode by `meta_addr` → seam yields surviving bytes + block-run list → orchestrator derives the allocated-block set once → classifies `intact`/`partial-overwritten` → hashes the written bytes → safe_extract writes `recovered/...` → CaseStore catalogs a recovered `files` row. Filtering slice: after walk + recovery, iterate `files` rows → for each, query NSRL/custom by md5→sha1→sha256 → CaseStore writes a neutral `known` annotation.

### Recommended Project Structure

```
src/pyautopsy/
├── evidence/
│   └── filesystem.py     # EXTEND: recover_meta(), iter_block_runs(), allocated_data_blocks(),
│                         #         orphan enumeration — all pytsk3, returning plain ints/closures
├── core/
│   ├── recover.py        # NEW: run_recover orchestrator (no pytsk3) — classify, hash, write, catalog
│   └── analyze.py         # EXTEND: opt-in recover/filter steps gated on supplied inputs (D-40)
├── filter/               # NEW package (or knownfiles.py module)
│   ├── nsrl.py           # NEW: read-only sqlite3 NSRL membership checker
│   └── hashsets.py       # NEW: custom allow/block list parsing + match model
├── case/
│   ├── store.py          # EXTEND: insert_recovered_files / known-match methods + get_* readers
│   └── schema.sql        # EXTEND (additive): recovery columns and/or known_file_matches table
├── report/
│   ├── assemble.py       # EXTEND: recovered / orphan / known sections (deterministic)
│   └── templates/report.html.j2   # EXTEND: new sections, autoescaped
└── cli/main.py           # EXTEND: `recover` command + `--nsrl`/`--hash-set` flags on recover/analyze
```

### Pattern 1: Reopen a deleted inode and read its surviving content (RECOV-01)
**What:** The TSK `icat` equivalent. `FS_Info.open_meta(inode=<meta_addr>)` reopens any inode by address regardless of allocation status; `File.read_random(offset, size)` returns the bytes the surviving data runs still point at.
**When to use:** For every deleted entry the Phase-2 walk recorded with a non-`None` `meta_addr` and `meta_type == "reg"`.
**Example:**
```python
# Source: VERIFIED live against pytsk3 20260520 on tests/fixtures/tiny_ext4.img
fs = pytsk3.FS_Info(img, offset=volume_offset)   # already done by open_fs()
f = fs.open_meta(inode=13)                         # deleted inode, by address
meta = f.info.meta                                  # addr=13, size=22, flags=UNALLOC, nlink=0
data = f.read_random(0, meta.size) if meta.size else b""
# -> b'this entry is deleted\n'   (exact original content recovered)
```
Caveat (seam contract): wrap `open_meta` in the seam and return a `RecoveredEntry` value object carrying a `read_random` closure (mirroring `FileEntry.read_random`) so **no native object escapes** `filesystem.py` (D-14). Hash the bytes via the existing `integrity.hash_file(reader, size)` — never re-implement hashing.

### Pattern 2: Confidence tier via derived allocated-block set (RECOV-03, D-30/D-31)
**What:** Decide `intact` vs `partial/overwritten` by testing whether the deleted file's data blocks have been reclaimed. pytsk3 has **no allocation-bitmap API**, so build the allocated-block set by walking every allocated inode's non-resident runs once, then intersect.
**When to use:** Once per filesystem (build the set), then per recovered file (intersect its runs).
**Example:**
```python
# Source: VERIFIED live on tiny_ext4.img — deleted inode 13 block {25}; allocated blocks {3..24};
#         intersection empty -> tier = "intact".
NONRES = int(pytsk3.TSK_FS_ATTR_NONRES)
SPARSE = int(pytsk3.TSK_FS_ATTR_RUN_FLAG_SPARSE)

def iter_block_runs(f):                 # f is a pytsk3.File (open_meta result)
    for attr in f:                      # File is iterable over its Attributes
        ai = attr.info
        if not (int(ai.flags) & NONRES):   # resident data (NTFS small files) has no blocks
            continue
        for run in attr:                # Attribute is iterable over TSK_FS_ATTR_RUN
            if int(run.flags) & SPARSE: # sparse runs occupy no real blocks
                continue
            yield from range(run.addr, run.addr + run.len)

def allocated_data_blocks(fs):
    ALLOC = int(pytsk3.TSK_FS_META_FLAG_ALLOC)
    blocks = set()
    for inum in range(fs.info.first_inum, fs.info.last_inum + 1):
        try:
            f = fs.open_meta(inode=inum)
        except OSError:
            continue
        m = f.info.meta
        if m is None or not (int(m.flags) & ALLOC):
            continue
        blocks.update(iter_block_runs(f))
    return frozenset(blocks)

# Classification (orchestrator, no pytsk3):
deleted_blocks = set(seam_run_list)          # plain ints from the seam
tier = "intact" if not (deleted_blocks & allocated_blocks) else "partial/overwritten"
```
**Tier-string design (D-30):** store the tier as a free-form string column/field whose current domain is `{"intact", "partial/overwritten"}`; a future `journal`/`carved` value is a new string, **no schema change**. Record the *rationale* (which/how many blocks overlapped, resident-data note, per-fs caveat) in `attributes` so the report never presents the tier as bare certainty (D-31/D-32).

### Pattern 3: Orphan-file identification (RECOV-02)
**What:** An orphan is a deleted entry whose parent directory is itself gone, so it has no path back to the root. TSK surfaces these two ways, both verified present:
1. The **`$OrphanFiles` virtual directory** (`TSK_FS_META_TYPE_VIRT_DIR`) — the Phase-2 walk already recurses into it (`walk_fs` docstring), so its children are already in `files`. Entries reached only via `$OrphanFiles` are orphans.
2. The per-inode **`TSK_FS_META_FLAG_ORPHAN`** flag on `meta.flags` (value 32) — set by TSK when an unallocated inode has no parent directory entry.
**When to use:** Mark a recovered entry orphan if it is reached under `$OrphanFiles` OR its `meta.flags & ORPHAN`. Phase 2 already stores `parent_addr`/`meta_addr`, so the orchestrator can also detect "parent_addr points at an inode that is itself unallocated/gone."
**Note:** In the committed `tiny_ext4.img` the deleted file's parent (root) survives, so it is a *normal deleted* entry, not an orphan — a Phase-4 fixture must add a file whose parent dir is deleted to exercise the orphan path (see Test Fixtures).
**Example:**
```python
# Source: VERIFIED — ORPHAN flag readable on meta.flags; $OrphanFiles present on ext4 + NTFS.
ORPHAN = int(pytsk3.TSK_FS_META_FLAG_ORPHAN)
is_orphan = bool(int(meta.flags) & ORPHAN)
```

### Pattern 4: NSRL RDS membership query, read-only, indexed (FILTER-01, D-36/D-37)
**What:** The modern NSRL RDS is distributed **only** as an RDSv3 SQLite database. The "minimal" variant exposes a `FILE` table with `md5`, `sha1`, `sha256` (plus `crc32`, `file_name`, `file_size`, `package_id`) columns; the full "modern" DB uses a `METADATA` table with the same hash columns. Query membership with stdlib `sqlite3`, opened **read-only** (`mode=ro` URI), matching md5→sha1→sha256 per D-37.
**When to use:** Post-walk pass over `files` rows that have hashes.
**Example:**
```python
# Source: CITED schema (NIST RDSv3 / hexacorn) + VERIFIED sqlite3 read-only URI idiom.
import sqlite3
conn = sqlite3.connect("file:" + nsrl_db_path + "?mode=ro", uri=True)  # read-only, never writes
# Defensive: discover which table/columns this distribution variant exposes.
tables = {r[0] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table'")}
hash_table = "FILE" if "FILE" in tables else "METADATA"   # minimal vs modern
# Membership by md5 first (NSRL is keyed on md5/sha1), then sha1, then sha256.
# IMPORTANT (Pitfall 4): RDSv3 stores hashes UPPERCASE; our files store lowercase hex.
row = conn.execute(
    f"SELECT 1 FROM {hash_table} WHERE md5 = ? LIMIT 1",
    (file_md5.upper(),)).fetchone()
known = row is not None
```
**Performance:** the hash columns are part of the RDSv3 primary key / are indexed, so a per-file `WHERE md5 = ?` lookup is an indexed probe — do **not** preload millions of rows into a Python set (memory). For very large case inventories, one prepared statement reused per row is sufficient; an optional `PRAGMA query_only=ON` reinforces read-only intent.

### Pattern 5: Custom allow/block hash-set parsing + neutral match model (FILTER-01, D-38)
**What:** Custom lists are newline-delimited hex hashes (allow vs block sense supplied by the flag). Infer algorithm by hex length: 32→MD5, 40→SHA-1, 64→SHA-256. Skip blank/comment lines; normalize case. A match is a neutral `known` annotation, never good/bad.
**Example:**
```python
# Source: stdlib parsing; model shape per D-38.
_HEX = {32: "md5", 40: "sha1", 64: "sha256"}
def parse_hash_set(text):
    out = {"md5": set(), "sha1": set(), "sha256": set()}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        h = line.split()[0].lower()          # tolerate "hash  filename" rows
        algo = _HEX.get(len(h))
        if algo and all(c in "0123456789abcdef" for c in h):
            out[algo].add(h)
    return out
# Annotation written via CaseStore (neutral, D-38):
#   {"known": {"source": "custom", "list": "<name>", "sense": "allow"|"block",
#              "matched_on": "md5"}}   — NO "good"/"bad"/"malicious" key anywhere.
```

### Anti-Patterns to Avoid
- **Asserting deletion intent.** Never write "user deleted X" or "good/bad/malicious" — only data-survival tiers and neutral "known" (D-32/D-38, mirrors Phase-3 WR-02).
- **Importing pytsk3 outside the seam.** `core/recover.py`, `filter/*` must not import pytsk3 — the `test_seam_allowlist.py` gate will fail. Add recover/run/bitmap helpers to `filesystem.py` only (D-14).
- **Raw SQL outside `store.py`.** All recovery rows + known annotations go through new `CaseStore` methods (D-08/D-35/D-39).
- **Writing recovered bytes outside the confinement jail / with an evidence-derived path.** Use `safe_extract`'s `_confined_target` + `_sanitize_name` and a deterministic volume+inode name (D-33/D-34); a deleted filename is adversarial input (it may contain `../`, control chars, the FAT first-char-lost `?`).
- **Hashing reclaimed blocks as if intact.** A `partial/overwritten` file's bytes came partly from another file's blocks — hash the recovered bytes but record the tier + provenance so the hash is never presented as the original file's integrity hash (mirrors `walk.py` `file_type_provenance`).
- **Re-sorting recovered/known lists outside the store.** Use the store's D-26 total order (D-41).
- **Leaking wall-clock into the report body.** New sections must carry zero run metadata (D-25/D-41).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Reading a deleted inode's content | Custom inode/extent parser | `FS_Info.open_meta` + `File.read_random` (seam) | TSK is the court-trusted implementation; CLAUDE.md forbids reimplementing TSK primitives. |
| Block-run enumeration | Manual extent-tree / FAT-chain walker | `File` attr iteration → `TSK_FS_ATTR_RUN` runs | TSK already decodes ext extents, NTFS runlists, FAT chains uniformly. |
| Single-pass MD5/SHA-1/SHA-256 | New hashing loop | existing `evidence/integrity.hash_file` | Already streams + handles short-read→None (D-17). |
| Confined file writes / name sanitization | `os.path.join` + ad-hoc cleanup | `util/safe_extract` `_confined_target` + `_sanitize_name` | Already hardened against traversal, control chars, drive anchors (INGEST-04). |
| NSRL DB access | Importing the whole DB / a 3rd-party NSRL lib | stdlib `sqlite3` read-only URI | D-36; NSRL is plain SQLite, indexed on hashes. |
| Content typing of recovered bytes | New magic logic | existing `evidence/filetype.file_type` | Reuse; head-bytes only, no native seam. |
| Deterministic ordering | Re-sort in the report | `CaseStore.get_*` ORDER BY (D-26) | Single source of ordering truth (CLI-02). |

**Key insight:** Every hard part of this phase already exists in-tree (recovery primitive, hashing, confinement, ordering, sole-writer persistence). Phase 4 is overwhelmingly **composition + classification logic + thin SQL/text parsing**, not new infrastructure. The one genuinely new mechanism — the derived allocated-block set — is ~15 lines and verified working.

## Runtime State Inventory

> Phase 4 is **additive code + additive schema**, not a rename/refactor/migration. No existing runtime state is renamed or relocated.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | New rows only: recovered `files` rows (`allocated=False` + recovery metadata) and known-file annotations. No existing rows are rewritten. The `recovered/` directory tree under the case dir is new on-disk output. | None — additive writes via CaseStore + safe_extract. |
| Live service config | None — verified by inspection (no external services; tool is a local CLI). | None. |
| OS-registered state | None — verified (no scheduled tasks, daemons, or registered services). | None. |
| Secrets/env vars | None — verified (no secrets; NSRL DB + hash-set paths are CLI arguments, not env). | None. |
| Build artifacts | Adding modules/columns does not stale any build artifact beyond a normal `pip install -e .` refresh; `schema.sql` changes apply to **fresh** case DBs only (CaseStore `create` runs the schema once — existing case DBs are not migrated, which is fine because `analyze` requires a fresh case dir, A2). | If any committed test fixture *case.db* exists it must be regenerated; verify none are committed (none found — fixtures are disk images, not case DBs). |

**Schema-migration note for the planner:** `CaseStore.create` applies `schema.sql` only at case-creation time; there is no migration path for an already-created `case.db`. Because `analyze` enforces a fresh case dir (A2) and `recover` runs against a case the same tool version created, additive columns/tables are safe. If recovery columns are added to `files`, use `... DEFAULT NULL` (additive, no backfill) so a pre-recovery walk row is valid.

## Common Pitfalls

### Pitfall 1: Expecting a block-allocation-bitmap API from pytsk3
**What goes wrong:** Reaching for `TSK_FS_BLOCK` / a `block_walk` to ask "is block N allocated?" The overwrite detector silently breaks.
**Why it happens:** TSK (the C library) has `tsk_fs_block_walk`, but **pytsk3 does not bind it** — `pytsk3.TSK_FS_BLOCK(fs)` constructs an object that is immediately invalid (`RuntimeError: Wrapped object ... no longer valid`), and there is no walker. [VERIFIED live]
**How to avoid:** Derive the allocated-block set by walking every allocated inode's non-resident runs once (Pattern 2). It is exact for the allocation question we need (is this block owned by an allocated file?).
**Warning signs:** Any code path constructing `TSK_FS_BLOCK` or calling a non-existent `block_walk`.

### Pitfall 2: ext4 zeroes block pointers on delete — most ext4 deletes recover as size-0
**What goes wrong:** On a real ext4 system, deleting a file **zeroes the inode's extent/block pointers**, so `read_random` returns nothing and `meta.size` may read 0 even though the inode survives. The tool appears to "fail to recover" healthy deletes.
**Why it happens:** ext4 (unlike ext3) clears `i_block` on unlink. The committed `tiny_ext4.img` recovers fully **only because `debugfs rm` leaves pointers intact** — a real `rm` on a mounted ext4 would not. This is a genuine forensic limitation, not a bug.
**How to avoid:** Treat "deleted ext4 entry with size 0 / no readable runs" as an honest `partial/overwritten` (or a distinct "metadata-only, no recoverable data") outcome and **say so** in the per-fs caveat (D-31). Do not overclaim ext4 recoverability. Record the caveat: "ext4 zeroes block pointers on unlink; full content recovery is the exception (debugfs-written fixtures) not the rule; carving (CARVE-01, deferred) is the path for zeroed-pointer ext4 deletes."
**Warning signs:** Reporting "intact" for an ext4 delete with zero readable bytes.

### Pitfall 3: FAT loses the first filename character; NTFS small files are resident (no blocks)
**What goes wrong:** (a) FAT zeroes the first character of a deleted directory entry's name (TSK substitutes `_`), so the recovered name is lossy — don't present it as authoritative, and sanitize it for the on-disk path. (b) NTFS resident files store `$DATA` **inside the MFT record** (verified: `tiny_ntfs.img` file1.txt $DATA attr is resident, size 27) — they have **no data-block runs**, so the block-overlap test yields an empty run set. A resident deleted file with an intact MFT record is `intact` even though `iter_block_runs` returns nothing.
**Why it happens:** Per-filesystem deletion semantics differ; the block-overlap classifier must special-case resident data.
**How to avoid:** When a recovered file has readable bytes but **no non-resident runs**, classify by MFT-record survival, not block overlap → `intact` with caveat "NTFS resident data recovered from MFT record." Record the FAT first-char-lost note in `attributes`.
**Warning signs:** Resident NTFS deletes mislabeled `partial/overwritten`; FAT `?`/`_` filenames used directly as write paths.

### Pitfall 4: NSRL RDSv3 stores hashes UPPERCASE; table name varies by variant
**What goes wrong:** Membership queries return zero matches because the project stores **lowercase** hex (Phase 2 `hashlib` `.hexdigest()`) while RDSv3 stores **UPPERCASE**; or the query hard-codes `FILE` and the examiner supplied the `modern` (full) DB whose table is `METADATA`.
**Why it happens:** Case mismatch + distribution-variant schema differences (minimal `FILE` vs modern `METADATA`).
**How to avoid:** Normalize the probe hash with `.upper()` (or normalize both sides consistently) and **discover the table** from `sqlite_master` before querying (Pattern 4). Add a test fixture NSRL-style SQLite DB with one known hash to lock this.
**Warning signs:** NSRL filtering silently matching nothing on a known-good system file.

### Pitfall 5: `open_meta` reallocation hazard — a reopened inode may now describe a *different* file
**What goes wrong:** After deletion the inode may have been reused by a new allocated file. `open_meta(inode=N)` then returns the **current** occupant, not the deleted one. Recovering "the deleted file" actually reads the new file's bytes.
**Why it happens:** Inode reuse. The Phase-2 walk recorded the deleted entry's `meta_addr` at walk time; by recover time the inode could be reallocated (within one read-only run this is stable, but the *name-vs-meta* allocation split matters).
**How to avoid:** Only recover entries the walk recorded as deleted (`allocated is False`, i.e. name OR meta unallocated) AND re-check `meta.flags & UNALLOC` at recover time. If the reopened inode is now `ALLOC`, treat it as reallocated → do not present its bytes as the deleted file's content (classify `partial/overwritten` / skip with a recorded reason). The single read-only pass keeps this consistent.
**Warning signs:** A "recovered" file whose reopened inode is allocated and whose content matches a live file.

### Pitfall 6: Determinism — inode-iteration + recovered-name collisions
**What goes wrong:** Two distinct deleted entries that reclaimed the same path/name produce colliding `recovered/` filenames, or recovered-row ordering varies between runs, breaking CLI-02.
**Why it happens:** Non-deterministic enumeration order or name-only keying.
**How to avoid:** Enumerate deleted entries in a deterministic order (iterate `files` rows in `get_files` id order, or inode-ascending). Name recovered files by **volume_id + volume_offset + meta_addr** (unique per inode) + sanitized name (D-34) so two entries never collide. Order all report lists via the store's D-26 total order (D-41). No wall-clock anywhere in the body.
**Warning signs:** `test_reproducibility`-style byte diff between two recover runs on the same fixture.

## Code Examples

### Recover a deleted inode through the seam (RECOV-01)
```python
# Source: VERIFIED live (pytsk3 20260520, tiny_ext4.img inode 13). Seam-side; returns a
# pytsk3-free RecoveredEntry so no native object escapes filesystem.py (D-14).
@dataclass(frozen=True, slots=True)
class RecoveredEntry:
    meta_addr: int
    size: int
    meta_type: str
    is_orphan: bool
    now_allocated: bool                       # reallocation hazard (Pitfall 5)
    data_blocks: tuple[int, ...]              # plain ints (Pattern 2)
    has_resident_data: bool                   # NTFS small-file (Pitfall 3)
    read_random: Callable[[int, int], bytes] | None

def recover_meta(fs, inode: int) -> RecoveredEntry | None:
    try:
        f = fs.open_meta(inode=inode)
    except OSError:
        return None
    m = f.info.meta
    if m is None:
        return None
    ALLOC = int(pytsk3.TSK_FS_META_FLAG_ALLOC)
    ORPHAN = int(pytsk3.TSK_FS_META_FLAG_ORPHAN)
    blocks, resident = _runs_and_residency(f)   # iter_block_runs + resident check
    return RecoveredEntry(
        meta_addr=int(m.addr), size=int(m.size),
        meta_type=_meta_type_label(int(m.type)),
        is_orphan=bool(int(m.flags) & ORPHAN),
        now_allocated=bool(int(m.flags) & ALLOC),
        data_blocks=tuple(sorted(blocks)),
        has_resident_data=resident,
        read_random=(lambda off, sz: f.read_random(off, sz)) if m.size else None,
    )
```

### Classify the confidence tier (RECOV-03, orchestrator — no pytsk3)
```python
# Source: VERIFIED logic (intersection test on tiny_ext4.img).
def classify_tier(entry, allocated_blocks: frozenset[int]) -> tuple[str, dict]:
    if entry.now_allocated:                       # Pitfall 5
        return "partial/overwritten", {"reason": "inode reallocated to a live file"}
    if not entry.data_blocks and entry.has_resident_data:
        return "intact", {"reason": "resident data recovered from MFT record"}
    if not entry.data_blocks and entry.size > 0:  # ext4 zeroed pointers (Pitfall 2)
        return "partial/overwritten", {"reason": "no recoverable data runs (pointers cleared)"}
    overlap = set(entry.data_blocks) & allocated_blocks
    if overlap:
        return "partial/overwritten", {"reason": "data blocks reallocated",
                                        "overlapping_blocks": sorted(overlap)[:32]}
    return "intact", {"reason": "all data blocks still unallocated"}
```

### Write recovered bytes through the confinement jail (RECOV-01, D-33/D-34)
```python
# Source: reuses util/safe_extract confinement helpers (verified present).
from pyautopsy.util.safe_extract import _confined_target, _sanitize_name
def recovered_path(case_dir, vol_id, vol_off, meta_addr, name):
    dest = (case_dir / "recovered" / f"vol{vol_id}-off{vol_off}").resolve()
    dest.mkdir(parents=True, exist_ok=True)
    safe_name = _sanitize_name(name) or "unnamed"
    rel = f"{meta_addr}-{safe_name}"             # deterministic, collision-safe (D-34)
    target = _confined_target(str(dest), rel)    # realpath confinement (D-33)
    return target
# Then stream entry.read_random into target while feeding integrity.hash_file the same reader.
```

### Hash the recovered bytes (RECOV-01, D-37 — reuse Phase 2)
```python
# Source: existing evidence/integrity.hash_file (single-pass MD5/SHA-1/SHA-256).
digests = integrity.hash_file(entry.read_random, entry.size, max_size=max_hash_size)
# digests == {"md5":..,"sha1":..,"sha256":..} or None on short read; store on the recovered FileRow.
```

### NSRL read-only membership probe (FILTER-01, D-36/D-37)
```python
# Source: CITED RDSv3 schema + VERIFIED sqlite3 read-only URI.
def open_nsrl(path):
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON;")
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    return conn, ("FILE" if "FILE" in tables else "METADATA")

def nsrl_match(conn, table, *, md5, sha1, sha256):
    for col, val in (("md5", md5), ("sha1", sha1), ("sha256", sha256)):  # D-37 order
        if not val:
            continue
        if conn.execute(f"SELECT 1 FROM {table} WHERE {col}=? LIMIT 1",
                        (val.upper(),)).fetchone():     # Pitfall 4: RDSv3 is uppercase
            return {"source": "nsrl", "matched_on": col}   # neutral (D-38)
    return None
```

### Custom allow/block list match (FILTER-01, D-38)
```python
# Source: stdlib; neutral known annotation (no good/bad).
def custom_match(parsed, sense, list_name, *, md5, sha1, sha256):
    for col, val in (("md5", md5), ("sha1", sha1), ("sha256", sha256)):
        if val and val.lower() in parsed[col]:
            return {"source": "custom", "list": list_name,
                    "sense": sense, "matched_on": col}   # sense in {"allow","block"}
    return None
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| NSRL RDS 2.XX flat text hash sets | RDSv3 SQLite databases (full + minimal, modern/legacy/android/iOS) | NIST completed the transition; current release 2026.03.1 | Query with `sqlite3`, not text parsing; minimal `FILE` table vs modern `METADATA` table. [CITED: NIST current-RDS page] |
| `wkhtmltopdf` / Autopsy GUI for reporting | Already settled in Phase 3 (Jinja2/JSON) | — | Phase 4 only extends the existing deterministic body. |

**Deprecated/outdated:**
- Any guidance assuming NSRL is a text/`.txt` hash set — superseded by RDSv3 SQLite (D-36).
- Assuming pytsk3 exposes `tsk_fs_block_walk` — it does not (Pitfall 1).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | NSRL RDSv3 stores hash hex values in **UPPERCASE** | Pitfall 4, Pattern 4 | If wrong (some variant lowercase), normalize-then-compare both sides handles it; mitigation already proposed (discover + a fixture DB locks the real behavior). Low residual risk. |
| A2 | The "minimal" variant uses a `FILE` table and "modern/full" uses `METADATA`; both carry `md5`/`sha1`/`sha256` columns | Pattern 4 | Mitigated by run-time `sqlite_master` table discovery + a column-existence check before querying. The exact column names should be confirmed against the examiner's actual DB during planning (or a committed fixture DB built to the published schema). |
| A3 | Real-ext4 `rm` zeroes block pointers (most ext4 content deletes are not recoverable metadata-intact) | Pitfall 2 | This is well-established ext4 behavior; if the planner under-weights it, the tool may overclaim recoverability. Drives the honest-caveat copy. |
| A4 | A single read-only recovery pass keeps inode allocation state stable enough that re-checking `meta.flags & UNALLOC` at recover time reliably catches reallocation | Pitfall 5 | The image is static and read-only, so allocation state does not change mid-run; risk is essentially nil for a fixed image. |

**Note:** A1/A2 are the only material assumptions; both are de-risked by run-time schema discovery + a small committed NSRL-format fixture DB the planner should add. Everything in the recovery/overwrite path is `[VERIFIED]` against the live binding.

## Open Questions

1. **Exact RDSv3 column names across all four "minimal" variants.**
   - What we know: minimal exposes a `FILE` table with `md5`/`sha1`/`sha256`/`crc32`/`file_name`/`file_size`/`package_id` (CITED). Modern full uses `METADATA`.
   - What's unclear: whether every minimal variant (android/iOS) uses identical column names.
   - Recommendation: discover table+columns from `sqlite_master`/`PRAGMA table_info` at open time (Pattern 4); build one committed NSRL-format fixture DB (a few rows) so the matcher is tested without the multi-GB real dataset.

2. **Column-vs-`attributes` split for recovery metadata + known matches (D-35/D-39).**
   - What we know: `files` already has `allocated`/`meta_addr`/hashes/`attributes`; `attributes` is the blackboard.
   - What's unclear: whether the report/query needs a first-class `recovered`/`confidence_tier` column for efficient filtering vs JSON-only.
   - Recommendation (planner's call): put the discriminators the report sections sort/group on (e.g. a `recovered` boolean, `confidence_tier`) as narrow additive columns for clean deterministic queries, and keep rationale/overwrite-evidence/known-match details in `attributes`. A dedicated `known_file_matches` table keeps multiple matches per file clean and preserves the sole-writer rule.

3. **Should orphan files be recovered (content) or only reported?**
   - What we know: RECOV-02 requires reporting orphans **separately**; recovery (RECOV-01) is metadata-intact.
   - Recommendation: recover content for orphans too when their data survives (same mechanism), but list them in a separate "Orphan Files" section (D-25 boundary): orphan-ness is a *provenance* fact, independent of the recovery tier.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `pytsk3` | recovery (open_meta/read_random/runs) | ✓ | 20260520 | — (hard requirement; already pinned) |
| `sqlite3` (stdlib) | NSRL filtering + case store | ✓ | bundled w/ Python 3.14 | — |
| `mkfs.ext4` + `debugfs` (e2fsprogs) | building the Phase-4 orphan/overwritten ext4 fixture | build-time only | host-dependent | committed fixture image (built once, like Phase 2) |
| `mkntfs` (ntfs-3g) | building an NTFS resident-delete fixture | build-time only | host-dependent | committed fixture image |
| `mkfs.fat` + `mcopy` (dosfstools/mtools) | building a FAT first-char-lost fixture | build-time only | host-dependent | committed fixture image |
| NSRL RDS SQLite DB | live FILTER-01 against real NSRL | ✗ (multi-GB, examiner-supplied) | 2026.03.1 latest | committed tiny NSRL-format fixture DB for tests |

**Missing dependencies with no fallback:** none (recovery + filtering run on stdlib + already-pinned pytsk3).
**Missing dependencies with fallback:** the real NSRL dataset is not present (by design, D-36) — tests use a committed tiny NSRL-format SQLite fixture; the mkfs tools are build-time-only and their outputs are committed (Phase-2 precedent).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (Python 3.14, `pytest 9.0.3`) [VERIFIED: pyproject `[dependency-groups] dev`, `tests/` cache] |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`pythonpath=["src"]`, `testpaths=["tests"]`) |
| Quick run command | `python -m pytest tests/test_recover.py tests/test_knownfiles.py -x -q` |
| Full suite command | `python -m pytest -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| RECOV-01 | Deleted ext4 inode recovers its exact bytes + per-file hashes; cataloged as a `files` row with `allocated=False`; bytes written under `recovered/` confined tree | unit + integration | `pytest tests/test_recover.py::test_recovers_deleted_ext4_content -x` | ❌ Wave 0 |
| RECOV-01 | NTFS resident `$DATA` recovers from MFT record (no runs) | unit | `pytest tests/test_recover.py::test_recovers_ntfs_resident -x` | ❌ Wave 0 |
| RECOV-02 | Orphan (parent dir deleted) reported in a separate orphan list, not the normal deleted list | integration | `pytest tests/test_recover.py::test_orphan_reported_separately -x` | ❌ Wave 0 |
| RECOV-03 | Intact file (no block overlap) → `intact`; a file whose blocks overlap an allocated file → `partial/overwritten`; ext4 zeroed-pointer delete → `partial/overwritten` with caveat; **no** "user deleted" copy anywhere | unit | `pytest tests/test_recover.py::test_confidence_tiers -x` | ❌ Wave 0 |
| RECOV-03 | Honesty: report/tier copy contains no intent/good-bad language (mirror Phase-3 WR-02 wording test) | unit | `pytest tests/test_recover.py::test_no_overclaiming_copy -x` | ❌ Wave 0 |
| FILTER-01 | NSRL fixture DB: a known md5 (uppercase in DB, lowercase in row) yields a neutral `known{source:nsrl}` annotation; non-member yields none | unit | `pytest tests/test_knownfiles.py::test_nsrl_membership -x` | ❌ Wave 0 |
| FILTER-01 | Custom allow + block lists parse (comments/blank/mixed-case) and match md5→sha1→sha256; annotation carries source+list+sense, never good/bad | unit | `pytest tests/test_knownfiles.py::test_custom_hash_sets -x` | ❌ Wave 0 |
| FILTER-01 | Table discovery handles both `FILE` and `METADATA` variants | unit | `pytest tests/test_knownfiles.py::test_variant_table_discovery -x` | ❌ Wave 0 |
| CLI-02 / D-41 | Two `recover`/`analyze --recover --nsrl` runs on the same fixture produce byte-identical report.json + identical `recovered/` filenames | integration | `pytest tests/test_reproducibility.py::test_recover_filter_reproducible -x` | ❌ Wave 0 (extend existing file) |
| D-40 | Default `analyze` (no recover/nsrl inputs) report stays byte-identical to the Phase-3 baseline | integration | `pytest tests/test_reproducibility.py::test_default_analyze_unchanged -x` | ❌ Wave 0 |
| D-14 | Seam allowlist still green (recover/filter modules import no pytsk3) | unit | `pytest tests/test_seam_allowlist.py -x` | ✅ exists |
| D-42 | Read-only: source image bytes unchanged after recover; re-verify still runs | integration | `pytest tests/test_readonly_guarantee.py::test_recover_does_not_write_source -x` | ❌ Wave 0 (extend existing file) |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_recover.py tests/test_knownfiles.py tests/test_seam_allowlist.py -x -q`
- **Per wave merge:** `python -m pytest -q` (full suite, incl. reproducibility + readonly guarantee)
- **Phase gate:** Full suite green before `/gsd-verify-work`; `ruff` + `mypy` clean (project gates).

### Wave 0 Gaps
- [ ] `tests/test_recover.py` — recovery, orphan, tier, honesty tests (covers RECOV-01/02/03)
- [ ] `tests/test_knownfiles.py` — NSRL + custom hash-set matching (covers FILTER-01)
- [ ] `tests/fixtures/make_fixtures.py` — extend with: ext4 image containing (a) an **orphan** (delete a file *and* its parent dir via `debugfs rmdir`/`rm`), (b) an **overwritten** deleted entry (delete a file, then write a new file that reclaims its blocks), and an NTFS image with a **resident deleted** file; record exact ground-truth constants (mirrors Phase-2 fixture pattern). Commit the built images.
- [ ] `tests/fixtures/` — a tiny **NSRL-format SQLite fixture** (`FILE` table, a couple of UPPERCASE-hash rows matching known fixture-file hashes) + a `METADATA`-variant copy for the discovery test; built deterministically at fixture-build time.
- [ ] Extend `tests/test_reproducibility.py` and `tests/test_readonly_guarantee.py` (files exist) with the recover/filter cases above.
- [ ] No framework install needed — pytest already present.

## Security Domain

> `security_enforcement: true`, ASVS level 1 (config). Evidence is adversarial input (deleted filenames especially).

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Local CLI, no auth surface. |
| V3 Session Management | no | No sessions. |
| V4 Access Control | no | No multi-user model. |
| V5 Input Validation / Sanitization | **yes** | Deleted filenames + custom-list + NSRL-path are untrusted. Sanitize recovered names via `safe_extract._sanitize_name`; confine writes via `_confined_target` (realpath); validate hash-set lines (hex-only, length∈{32,40,64}); open NSRL DB read-only (`mode=ro`, `PRAGMA query_only`); parameterize all SQL (`?` placeholders) — never string-format a hash into SQL. |
| V6 Cryptography | partial | Reuse stdlib `hashlib` via `integrity.hash_file`; never hand-roll. Hashes here are integrity/identity, not secrets. |

### Known Threat Patterns for {pytsk3 recovery + sqlite3 filtering}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Path traversal via a deleted filename (`../../x`, control chars, FAT `?`/`_`, absolute) used as a write path | Tampering | `_sanitize_name` + `_confined_target` realpath confinement; deterministic `vol/off/inode-name` scheme (never the raw name) (D-33/D-34). |
| Recovered-content decompression/size bomb (a huge sparse/deleted file) exhausting disk | DoS | Honor `max_hash_size`; cap recovered write size (reuse `ExtractionLimits` ethos); sparse runs skipped (Pattern 2). |
| SQL injection into the NSRL query | Tampering | Parameterized `?` placeholders only; table name chosen from a fixed `{FILE, METADATA}` allowlist, never interpolated from user input beyond that set. |
| Malicious NSRL DB path (write/attach side effects) | Tampering/Elevation | Open with `?mode=ro` + `PRAGMA query_only=ON`; never `ATTACH`; treat the file as read-only evidence-adjacent input. |
| Writing to / altering the evidence source during recovery | Tampering (forensic soundness) | All reads via the seam's `read_random` (no mount, no write); only the case dir is written; Phase-1 re-verify runs end-of-run (D-42). |
| Inode-reuse confusion presenting a live file as "recovered deleted" | Spoofing of findings | Re-check `meta.flags & UNALLOC` at recover time; classify reallocated inodes as overwritten (Pitfall 5). |

## Project Constraints (from CLAUDE.md)

- **Wrap pytsk3, never reimplement TSK** primitives (carving/parsing/recovery). Recovery uses `open_meta`/`read_random`; carving stays deferred (CARVE-01).
- **Single native-seam allowlist (D-14):** only `evidence/image.py` + `evidence/filesystem.py` may import `pytsk3`/`pyewf`; `test_seam_allowlist.py` enforces it. Add recover/run/bitmap helpers to `filesystem.py`.
- **CaseStore is the sole DB writer (D-08):** no raw SQL outside `store.py`. New recovered-row + known-match writes go through new store methods.
- **Forensic soundness:** source read-only, never mounted/written; findings hashable/reproducible; **never** assert intent or good/bad (D-32/D-38).
- **UTC everywhere / deterministic report body:** new sections carry no wall-clock; ordered by the store's D-26 total order (CLI-02/D-41).
- **SHA-256 primary, MD5/SHA-1 also computed** (already done in Phase 2) — used for NSRL keying (MD5/SHA-1 first per D-37).
- **NSRL is a large external SQLite dataset, not a pip install** (queried via stdlib `sqlite3`); fuzzy hashing is out of scope here.

## Sources

### Primary (HIGH confidence)
- Installed `pytsk3` 20260520 — `open_meta`, `read_random`, `File`/`Attribute`/`TSK_FS_ATTR_RUN` iteration, `TSK_FS_META_FLAG_ORPHAN/UNALLOC/ALLOC`, `TSK_FS_INFO` (`first_inum`/`last_inum`/`block_size`), absence of usable `TSK_FS_BLOCK`/`block_walk` — all exercised live against `tests/fixtures/tiny_ext4.img` and `tiny_ntfs.img`.
- Codebase: `src/pyautopsy/evidence/filesystem.py`, `core/walk.py`, `core/analyze.py`, `case/store.py`, `case/schema.sql`, `util/safe_extract.py`, `report/{assemble,jsonreport,htmlreport}.py`, `cli/main.py`, `tests/fixtures/make_fixtures.py`, `tests/test_seam_allowlist.py`, `pyproject.toml`.
- `.planning/phases/04-.../04-CONTEXT.md` (D-29..D-42), `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md` Phase 4.

### Secondary (MEDIUM confidence)
- NIST — Current RDS Hash Sets (RDSv3 SQLite only; minimal vs full; latest 2026.03.1): https://www.nist.gov/itl/ssd/software-quality-group/national-software-reference-library-nsrl/nsrl-download/current-rds
- NIST — RDSv3 documentation (PDF): https://s3.amazonaws.com/rds.nsrl.nist.gov/RDS/RDSv3_Docs/RDSv3.pdf
- Hexacorn — Analysing NSRL data set, Part 3 (RDSv3 schema: METADATA/PACKAGE_OBJECT; FILE minimal table; UPPER() usage): https://www.hexacorn.com/blog/2023/09/16/analysing-nsrl-data-set-for-fun-and-because-curious-part-3/
- AskClees — Importing NSRL V3 hashsets (minimal `FILE` table md5/sha1/sha256 columns): https://askclees.com/2023/04/05/importing-nsrl-v3-hashsets-into-legacy-tools/

### Tertiary (LOW confidence)
- Exact RDSv3 hash case (UPPERCASE) and per-variant column identity — inferred from the above + community tooling; de-risked by run-time `sqlite_master`/`PRAGMA table_info` discovery and a committed fixture DB (Open Question 1, Assumptions A1/A2).

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new deps; recovery primitive + run iteration verified live on the installed binding.
- Architecture / recovery mechanism: HIGH — `open_meta`/`read_random`/run-overlap classification round-tripped real fixture bytes; orphan flag + `$OrphanFiles` confirmed present.
- Overwrite detection: HIGH — derived allocated-block set verified (pytsk3 block-bitmap absence confirmed, so this is the correct approach, not a guess).
- NSRL filtering: MEDIUM — schema/format CITED from NIST + community; exact table/column/case de-risked by run-time discovery + a fixture DB.
- Pitfalls: HIGH — ext4 pointer-zeroing, NTFS residency, FAT first-char-lost, inode reuse, and the bitmap-API absence are all grounded in verified behavior or established filesystem semantics.

**Research date:** 2026-05-31
**Valid until:** ~2026-06-30 (stable: pytsk3 pinned; NSRL releases quarterly — re-confirm schema if targeting a newer RDS than 2026.03.1).
