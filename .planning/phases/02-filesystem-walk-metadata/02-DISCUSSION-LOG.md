# Phase 2: Filesystem Walk & Metadata - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-31
**Phase:** 2-Filesystem Walk & Metadata
**Areas discussed:** Native-seam boundary, Volume/partition scope, MACB & timestamp source, File-type signature dep, Per-file hashing scope, Deleted/unallocated boundary

---

## Native-seam boundary

| Option | Description | Selected |
|--------|-------------|----------|
| Allowlist of seam modules | Keep image.py byte-layer only; add evidence/filesystem.py for FS_Info/Volume_Info/Directory; update D-06 grep gate to a documented allowlist | ✓ |
| Extend image.py | Put FS-layer functions in the existing single file; gate stays literally single-file | |

**User's choice:** Allowlist of seam modules
**Notes:** Separates byte-layer from FS-layer concerns; D-06 invariant becomes "native calls confined to the allowlist." → D-14

---

## Volume / partition scope

| Option | Description | Selected |
|--------|-------------|----------|
| Enumerate all volumes | Volume_Info enumerate every partition, walk each supported FS, tag rows with volume id/offset; bare-FS fallback at offset 0; unsupported/encrypted → known-limitation finding | ✓ |
| Single partition MVP | Walk one FS only (largest or --partition); defer multi-volume | |

**User's choice:** Enumerate all volumes
**Notes:** Real evidence disks are partitioned; satisfies success-criterion 5. → D-15, D-20

---

## MACB & timestamp source

| Option | Description | Selected |
|--------|-------------|----------|
| TSK standard MACB + source tag | TSK meta MACB → tz-aware UTC, timestamp_source string; FAT via --timezone (default UTC) flagged local-time-inferred; NTFS $FILE_NAME deferred | ✓ |
| Also capture NTFS $FILE_NAME set | Additionally parse $FILE_NAME timestamps (timestomping signal), store both sets — more native attribute work | |

**User's choice:** TSK standard MACB + source tag
**Notes:** Covers META-02 honestly without deep attribute parsing; $FILE_NAME deferred. → D-16

---

## File-type signature dep

| Option | Description | Selected |
|--------|-------------|----------|
| libmagic (python-magic) | Court-recognized forensic standard, broad/accurate; document as native dep alongside libtsk/libewf | ✓ |
| puremagic (pure-Python) | Zero system deps, lightest install; smaller coverage, less authoritative | |
| Hand-rolled magic table | No deps, fully inspectable; weakest coverage | |

**User's choice:** libmagic (python-magic)
**Notes:** Forensic defensibility outweighs the extra native dep (project already documents native deps). → D-19

---

## Per-file hashing scope

| Option | Description | Selected |
|--------|-------------|----------|
| Hash all regular files, single pass | All three digests in one streaming pass; zero-length → empty sentinel; non-regular → no hash; no default cap but configurable --max-hash-size | ✓ |
| Hash with default size cap | Same but skip files above a default threshold | |
| You decide | Planner picks defaults consistent with D-07 | |

**User's choice:** Hash all regular files, single pass
**Notes:** Complete, defensible inventory; runtime tunable via --max-hash-size. → D-17

---

## Deleted / unallocated boundary

| Option | Description | Selected |
|--------|-------------|----------|
| Record status, defer recovery | Record every entry incl. deleted with allocated/unallocated status + inode/MFT; no recovery/carving/tiers (Phase 4); hash unallocated only if trivially intact | ✓ |
| Allocated-only this phase | Inventory only live files; defer all unallocated handling to Phase 4 | |

**User's choice:** Record status, defer recovery
**Notes:** Satisfies META-01 status requirement while keeping a clean Phase 4 boundary. → D-18

---

## Claude's Discretion

- Exact `files` table schema (typed columns vs JSON attributes split), consistent with Phase 1 D-02
- Path normalization/representation and recursion strategy
- Streaming-hash chunk size and default `--max-hash-size`
- Progress reporting style (Rich) for large-image walks
- CLI surface for the walk (new subcommand vs fold-in), consistent with D-12

## Deferred Ideas

- NTFS `$FILE_NAME` dual-timestamp capture + timestomping detection
- Deleted-file content recovery, orphans, confidence tiers, carving → Phase 4
- NSRL / custom hash-set filtering → Phase 4
- Timeline + HTML/JSON report + single-command `analyze` → Phase 3
- NTFS ADS, resident/non-resident, sparse-file specifics → revisit if a fixture needs it
- BitLocker/LUKS decryption (vs. reporting encrypted) → v2
