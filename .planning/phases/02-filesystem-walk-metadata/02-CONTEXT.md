# Phase 2: Filesystem Walk & Metadata - Context

**Gathered:** 2026-05-31
**Status:** Ready for planning

<domain>
## Phase Boundary

This phase delivers the **second forensic source-of-truth**: a complete,
normalized, per-file inventory of every supported filesystem in an image,
written into the Phase 1 case store. It feeds the Phase 3 timeline. In scope
(maps META-01..05):

- Walk **ext4 / NTFS / FAT** filesystems and inventory **every** entry — path,
  size, inode/MFT address, allocated/unallocated status — as normalized
  `files` rows in the case store (META-01)
- **MACB timestamps per file**, tz-aware UTC ISO-8601 with explicit offset,
  recording original timezone and timestamp source; no naive/local datetimes
  in the pipeline (META-02)
- **Ownership (UID/GID) and permission/mode bits** per file (META-03)
- **MD5 + SHA-1 + SHA-256 per file**, computed during the walk in a single
  streaming pass (META-04)
- **File type by content signature** (not extension) (META-05)
- **Encrypted/unsupported volumes** reported as an explicit known-limitation
  finding — never empty or garbage output (success-criterion 5)

Out of scope (later phases): deleted-file **content recovery**, orphan-tree
reconstruction, confidence tiers, carving, NSRL/hash-set filtering (Phase 4);
timeline construction + HTML/JSON report rendering + single-command `analyze`
(Phase 3); log parsing / super-timeline / search (Phase 5). This phase records
allocated/unallocated **status** only — it does not recover.

</domain>

<decisions>
## Implementation Decisions

### Native Seam (extends Phase 1 D-06)
- **D-14:** The single-native-seam rule evolves from "only `evidence/image.py`
  imports pytsk3" to **"native pytsk3/pyewf calls are confined to an explicit,
  documented seam allowlist."** `evidence/image.py` stays **byte-layer only**
  (`Img_Info`, raw + EWF, `ImageHandle`). A **new native module** (e.g.
  `evidence/filesystem.py`) owns the FS-layer surface: `Volume_Info`,
  `FS_Info`, `Directory`, `File` walking. The D-06 grep gate is updated to
  permit this small allowlist rather than a single file. Rationale: byte-layer
  and filesystem-layer are distinct concerns; folding both into one file would
  bloat it and mix abstractions.

### Volume / Partition Scope
- **D-15:** **Enumerate all volumes.** Use `Volume_Info` (mmls equivalent) to
  enumerate every partition; walk each **supported** filesystem; tag each file
  row with its **volume id / byte-offset** so a file is always traceable to its
  source volume. **Bare-filesystem images** (no partition table) fall back to
  opening the FS at offset 0. Real evidence disks are partitioned, and
  enumerating volumes is what makes success-criterion 5 (report
  encrypted/unsupported volumes) meaningful.

### MACB Timestamps & Source (META-02)
- **D-16:** Record the **TSK meta MACB times** (crtime/mtime/atime/ctime),
  normalized to **tz-aware UTC ISO-8601 with explicit offset**. Store a
  **`timestamp_source`** string per file capturing fs-type + originating
  attribute (e.g. `ext4:inode`, `ntfs:$STANDARD_INFORMATION`,
  `fat:dir-entry`). **FAT stores local time with no embedded timezone** →
  convert using a **`--timezone` CLI option (default UTC)** and **flag the
  values as `local-time-inferred`** in attributes so the report never
  overclaims precision. NTFS `$FILE_NAME` dual-timestamp set is **deferred**
  (note in JSON attributes only if trivially cheap; full $FN parsing /
  timestomping detection is a later concern).

### Per-File Hashing (META-04)
- **D-17:** **Hash all allocated regular files in a single streaming pass** —
  MD5 + SHA-1 + SHA-256 computed together over one read (reuse the Phase 1
  D-07 chunked single-pass pattern). **Zero-length files** record the
  well-known empty-file digests (sentinel). **Directories, devices, symlinks,
  and other non-regular entries get no content hash.** No size cap by default,
  but expose a configurable **`--max-hash-size`** for tuning runtime on huge
  media. File content is read **read-only via the TSK `File` object** (never by
  mounting), preserving the Phase 1 read-only guarantee.

### Deleted / Unallocated Boundary (META-01 vs Phase 4)
- **D-18:** During the walk, **record every entry TSK yields, including deleted
  ones**, with allocated/unallocated **status** and inode/MFT address, in the
  `files` table. **Do NOT** attempt content recovery, carving, orphan-tree
  reconstruction, or confidence tiers — those are Phase 4. Hash unallocated
  entries **only** if metadata+data are trivially intact via a normal read;
  otherwise leave hashes null. This satisfies META-01's allocated/unallocated
  status while keeping a clean Phase 4 boundary.

### File-Type Identification (META-05)
- **D-19:** Identify file type by **content signature via libmagic
  (`python-magic`)** — the court-recognized forensic standard with broad,
  accurate signatures. Document libmagic as a **native system dependency**
  alongside `libtsk`/`libewf` (README + Containerfile). Identification reads
  the file's leading bytes through the TSK `File` object (read-only), not by
  extension.

### Encrypted / Unsupported Volume Handling
- **D-20:** When `FS_Info` cannot open a volume (encrypted e.g. BitLocker/LUKS,
  or an unsupported filesystem), record it as an **explicit known-limitation
  finding** (volume id/offset + detected type + reason) rather than failing the
  run or emitting empty rows. The walk continues to other volumes.

### Claude's Discretion
- Exact `files` table schema — column names, which fields are typed columns vs
  JSON `attributes` — planner/executor decide, consistent with Phase 1 D-02
  (typed core columns + JSON `attributes`).
- Path normalization/representation (full path string vs path + parent inode),
  recursion strategy (recursive `Directory` walk vs TSK walk helpers).
- Chunk size for streaming per-file hashing; default `--max-hash-size`
  threshold — pick sane defaults, make configurable.
- Progress reporting style for large-image walks (Rich progress is already in
  the stack) — optional, planner's call.
- Whether to expose Phase 2 as a new subcommand (e.g. `pyautopsy walk` /
  `inventory`) or fold into existing CLI — consistent with D-12 Typer surface;
  the single-command `analyze` pipeline still lands in Phase 3.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project specs
- `.planning/PROJECT.md` — product definition, core value, constraints
  (forensic soundness, read-only, Linux CLI)
- `.planning/REQUIREMENTS.md` — Phase 2 maps **META-01..05** (definitions of
  inventory, MACB/UTC, ownership/perms, per-file hashes, signature typing)
- `.planning/ROADMAP.md` §"Phase 2: Filesystem Walk & Metadata" — goal + 5
  success criteria (the acceptance bar)

### Research (drives the decisions above)
- `.planning/research/STACK.md` — pytsk3 FS/volume API, libmagic/file-typing
  options, native dependency posture, version pinning
- `.planning/research/ARCHITECTURE.md` — case-store schema (typed columns +
  JSON attributes), single-native-seam isolation, read-only evidence handling,
  normalized forensic-event/file model
- `.planning/research/PITFALLS.md` — P1 (never mount source), P4
  (UTC-everywhere — esp. FAT local-time), timestamp-source / NTFS dual-time
  caveats, defensibility/no-overclaiming
- `.planning/research/SUMMARY.md` — cross-cutting synthesis and phase ordering

### Phase 1 foundation (the substrate this phase extends)
- `.planning/phases/01-forensic-foundation/01-CONTEXT.md` — locked decisions
  D-01..D-13 (case store, single seam, UTC-everywhere, hashing pattern)
- `src/pyautopsy/case/store.py` — `CaseStore` (typed columns + JSON
  `attributes`; `transaction()`, insert/get helpers) — Phase 2 adds the
  `files` table + insert path here
- `src/pyautopsy/evidence/image.py` — single native seam: `ImageHandle` /
  `ReadableImage` (read/get_size/close), `detect_format`, `tsk_version`,
  raw + EWF open — Phase 2's FS module sits beside this under the seam allowlist
- `src/pyautopsy/core/ingest.py` — `run_ingest` orchestrator + `IngestResult` —
  the walk hangs off the same case/evidence-source the ingest creates
- `src/pyautopsy/evidence/integrity.py` — single-pass MD5/SHA-256 streaming
  pattern (D-07) to mirror for per-file SHA-1 too

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`CaseStore`** (`case/store.py`): typed-columns + JSON `attributes` schema,
  `transaction()` context manager, `insert_*`/`get_*` helpers. Phase 2 adds a
  `files` table and an `insert_file` (or bulk-insert) path in the same style.
- **`evidence/image.py`**: `open_image()` → `ImageHandle` (`ReadableImage`
  protocol) gives the read-only byte source `FS_Info` needs; `tsk_version()`
  already probes the TSK version string for the COC record.
- **Integrity streaming-hash pattern** (`evidence/integrity.py`): one pass,
  multiple digests — extend the same idea to per-file MD5/SHA-1/SHA-256.
- **UTC helper** (Phase 1, D-10): reuse for all MACB normalization.

### Established Patterns
- **Single native seam, grep-enforced (D-06)** — Phase 2 *evolves* this into a
  documented allowlist (D-14); the gate must be updated, not bypassed.
- **UTC-everywhere, tz-aware, no naive datetimes (D-10)** — binding constraint
  on all MACB handling.
- **Read-only, never mount (D-05)** — file content + signature reads go through
  the TSK `File` object, never a mount.
- **src layout, pytest with `tmp_path` fixtures, ruff + mypy, pinned native
  deps (D-13)** — Phase 2 adds small fixture images (ext4/NTFS/FAT with known
  files + a deleted entry) as golden test data.

### Integration Points
- New `files` rows are the integration surface Phase 3 (timeline) and Phase 4
  (recovery/filtering) read from. The schema decided here is consumed
  downstream — keep it normalized and consistent with the Phase 1
  attributes model.

</code_context>

<specifics>
## Specific Ideas

- Forensic honesty over completeness: FAT local-time and any inferred value
  must be **flagged**, and encrypted/unsupported volumes must be **surfaced as
  findings** — the report must never imply precision or coverage it doesn't have.
- The walk is the "second source-of-truth" feeding the timeline — its row shape
  should anticipate Phase 3's timeline and Phase 4's recovery without
  pre-building them.

</specifics>

<deferred>
## Deferred Ideas

- NTFS `$FILE_NAME` dual-timestamp capture + timestomping detection → later
  (note in attributes only if trivially cheap now)
- Deleted-file **content recovery**, orphan reconstruction, confidence tiers,
  carving → **Phase 4**
- NSRL / custom hash-set filtering → **Phase 4**
- Timeline construction + HTML/JSON report + single-command `analyze` → **Phase 3**
- Alternate Data Streams (NTFS ADS), resident-vs-non-resident nuances, sparse-file
  specifics beyond basic hashing → revisit if a fixture surfaces the need
- BitLocker/LUKS *decryption* (vs. merely reporting the volume as encrypted) → v2

</deferred>

---

*Phase: 2-Filesystem Walk & Metadata*
*Context gathered: 2026-05-31*
