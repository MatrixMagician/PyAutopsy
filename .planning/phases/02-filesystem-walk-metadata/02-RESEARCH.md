# Phase 2: Filesystem Walk & Metadata - Research

**Researched:** 2026-05-31
**Domain:** Filesystem forensics — pytsk3 volume/FS walk, MACB normalization, per-file hashing, content-signature typing
**Confidence:** HIGH (pytsk3 API empirically verified on real ext4/NTFS/FAT32 fixtures with the installed pytsk3 4.15.0; python-magic API verified in an isolated venv)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-14:** Native pytsk3/pyewf calls are confined to an explicit, documented **seam allowlist** (evolves D-06). `evidence/image.py` stays **byte-layer only** (`Img_Info`, raw + EWF, `ImageHandle`). A **new native module** (e.g. `evidence/filesystem.py`) owns the FS-layer surface: `Volume_Info`, `FS_Info`, `Directory`, `File` walking. The D-06 grep gate is updated to permit this small allowlist rather than a single file.
- **D-15:** **Enumerate all volumes** via `Volume_Info` (mmls equivalent); walk each **supported** filesystem; tag each file row with its **volume id / byte-offset**. **Bare-filesystem images** (no partition table) fall back to opening the FS at offset 0.
- **D-16:** Record TSK meta MACB times (crtime/mtime/atime/ctime) normalized to **tz-aware UTC ISO-8601 with explicit offset**. Store a **`timestamp_source`** string per file (fs-type + originating attribute, e.g. `ext4:inode`, `ntfs:$STANDARD_INFORMATION`, `fat:dir-entry`). **FAT stores local time** → convert using a **`--timezone` CLI option (default UTC)** and **flag values as `local-time-inferred`**. NTFS `$FILE_NAME` dual-timestamp set is **deferred** (note in attributes only if trivially cheap).
- **D-17:** **Hash all allocated regular files in a single streaming pass** — MD5 + SHA-1 + SHA-256 together over one read (reuse the Phase 1 D-07 chunked pattern). **Zero-length files** record the well-known empty-file digests (sentinel). **Directories, devices, symlinks, other non-regular entries get no content hash.** No size cap by default, expose configurable **`--max-hash-size`**. Content read **read-only via the TSK `File` object** (never mounting).
- **D-18:** During the walk, **record every entry TSK yields, including deleted ones**, with allocated/unallocated **status** and inode/MFT address. **Do NOT** attempt content recovery, carving, orphan-tree reconstruction, or confidence tiers — those are Phase 4. Hash unallocated entries **only** if metadata+data are trivially intact via a normal read; otherwise leave hashes null.
- **D-19:** Identify file type by **content signature via libmagic (`python-magic`)**. Document libmagic as a **native system dependency** alongside `libtsk`/`libewf`. Read leading bytes through the TSK `File` object (read-only), not by extension.
- **D-20:** When `FS_Info` cannot open a volume (encrypted/unsupported), record it as an **explicit known-limitation finding** (volume id/offset + detected type + reason) rather than failing the run or emitting empty rows. The walk continues to other volumes.

### Claude's Discretion
- Exact `files` table schema — column names, typed columns vs JSON `attributes` — consistent with Phase 1 D-02.
- Path normalization/representation (full path string vs path + parent inode); recursion strategy.
- Chunk size for streaming per-file hashing; default `--max-hash-size` threshold.
- Progress reporting style for large-image walks (Rich is already in the stack) — optional.
- Whether Phase 2 is a new subcommand (`walk`/`inventory`) or folds into existing CLI — consistent with D-12 Typer surface; single-command `analyze` lands in Phase 3.

### Deferred Ideas (OUT OF SCOPE)
- NTFS `$FILE_NAME` dual-timestamp capture + timestomping detection → later.
- Deleted-file **content recovery**, orphan reconstruction, confidence tiers, carving → **Phase 4**.
- NSRL / custom hash-set filtering → **Phase 4**.
- Timeline construction + HTML/JSON report + single-command `analyze` → **Phase 3**.
- Alternate Data Streams (NTFS ADS), resident-vs-non-resident nuances, sparse-file specifics beyond basic hashing → revisit only if a fixture surfaces the need.
- BitLocker/LUKS *decryption* (vs. merely reporting the volume as encrypted) → v2.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| META-01 | Walk filesystem; inventory every file (path, size, inode/MFT addr, allocated/unallocated status) on ext4/NTFS/FAT | `Volume_Info` enumeration + `FS_Info(offset=)` + recursive `open_dir`/`as_directory` walk; `entry.info.name.flags` (ALLOC/UNALLOC) + `entry.info.meta.flags` give status; `meta.addr` is inode/MFT address. Verified on ext4/NTFS/FAT32 fixtures. |
| META-02 | MACB per file, normalized UTC, original tz + timestamp source captured | `meta.crtime/mtime/atime/ctime` (+ `*_nano`) are epoch ints; `from_epoch_utc()` already exists (timeutil); `fs.info.ftype` distinguishes FAT (local time) from ext4/NTFS (UTC); `timestamp_source` + `local-time-inferred` flag per D-16. |
| META-03 | Ownership (UID/GID) + permission/mode bits per file | `meta.uid`, `meta.gid`, `meta.mode` verified present on all three filesystems. |
| META-04 | Per-file MD5 + SHA-1 + SHA-256 during the walk (single pass) | Extend the D-07 single-pass pattern (integrity.py) to add SHA-1; read content via `File.read_random(offset, size)` in chunks. Empty-file sentinels precomputed. |
| META-05 | File type by content signature (not extension) | `python-magic` `magic.from_buffer(head_bytes, mime=True)` on the file's leading bytes read through the TSK `File` object. API verified. |
</phase_requirements>

## Summary

Phase 2 is a focused, well-bounded extension of a proven Phase 1 substrate. The native forensic engine (`pytsk3` 4.15.0) is **installed and the entire FS-walk API was verified empirically** during this research against real ext4, NTFS, and FAT32 fixtures built without root. There are no unknowns in the core API: `Volume_Info` enumerates partitions (and raises `OSError` on a bare-FS image, which is the documented signal to fall back to offset 0); `FS_Info(img, offset=)` opens a filesystem and **raises `OSError` when it can't determine the FS type** (the D-20 encrypted/unsupported signal); `fs.open_dir()` + per-entry `as_directory()` gives recursive walking; and `entry.info.name` / `entry.info.meta` expose every attribute the five META requirements need.

The single material packaging gotcha: the host currently has **`file-magic` 0.4.0** installed (the freedesktop binding, which has `magic.Magic` but **no** `magic.from_buffer`), NOT **`python-magic`** (the D-19 choice, which provides `magic.from_buffer`). These two distributions both import as `magic` and have **incompatible APIs**. The plan must add `python-magic==0.4.27` to `[project.dependencies]` and the runtime must defend against the wrong binding being importable. `python-magic` passes slopcheck `[OK]`.

**Primary recommendation:** Create `src/pyautopsy/evidence/filesystem.py` as the new FS-layer native seam (D-14), exposing a pure-Python generator of plain `FileEntry` value objects (mirroring how `image.py` yields `ImageHandle`). Drive the walk from a new `core/walk.py` orchestrator that reuses `CaseStore.transaction()` for bulk inserts, reuses `timeutil.from_epoch_utc`, and extends the `integrity.py` single-pass hasher to a 3-digest variant. Keep all `pytsk3` types behind the seam so the walk orchestrator, hashing, typing, and case-store tiers stay unit-testable with fakes — exactly the Phase 1 architecture.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Partition/volume enumeration | Native FS seam (`evidence/filesystem.py`) | — | Only the seam may touch `pytsk3.Volume_Info` (D-14). |
| Filesystem open + FS-type detection | Native FS seam | — | `FS_Info` is native; its `OSError` is the D-20 signal, translated to a plain finding at the seam edge. |
| Directory recursion + entry yield | Native FS seam | — | `open_dir`/`as_directory`/`open_meta` are native; seam yields plain `FileEntry` value objects. |
| MACB→UTC normalization | Pure-Python util (`util/timeutil`) | Walk orchestrator | `from_epoch_utc` already exists; orchestrator decides FAT local-time handling. |
| Per-file 3-digest hashing | Pure-Python integrity (`evidence/integrity.py`) | Walk orchestrator | Streaming hash logic is native-free; consumes bytes from the seam's `File` reader. |
| Content-signature typing | Pure-Python typing helper (e.g. `evidence/filetype.py`) | Walk orchestrator | `python-magic` is not a native *binding* in the pytsk3 sense; it wraps libmagic and is allowed outside the pytsk3 seam. Keep it isolated for testability. |
| Bulk persistence of `files` rows | Case store (`case/store.py`) | Walk orchestrator | All DB writes go through `CaseStore` (no raw SQL elsewhere). Phase 2 adds the `files` table + `insert_file`/`insert_files`. |
| Encrypted/unsupported finding rows | Case store (findings/limitations) | Walk orchestrator | A new `findings`/`limitations` row (or `files`-adjacent table) records D-20 limitations. |
| Walk orchestration + audit | Walk orchestrator (`core/walk.py`) | Audit log | Mirrors `core/ingest.py`: compose seam + hashing + typing + store + audit. |
| CLI surface | CLI (`cli/main.py`) | — | New `walk`/`inventory` subcommand (Claude's discretion), thin shell over the orchestrator. |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytsk3 | 20260520 (installed 4.15.0 libtsk) | Volume/FS/Directory/File walk, MAC times, deleted entries | Already the project's mandated, court-trusted engine (CLAUDE.md, D-06). API verified empirically this session. `[VERIFIED: empirical probe + PyPI]` |
| python-magic | 0.4.27 | Content-signature file typing (`from_buffer`) | D-19 choice; the de-facto libmagic Python wrapper exposing `from_buffer(buf, mime=...)`. `[VERIFIED: PyPI + isolated-venv API probe + slopcheck OK]` |
| hashlib (stdlib) | stdlib | MD5/SHA-1/SHA-256 per file | Reuse the Phase 1 D-07 single-pass pattern, adding SHA-1. `[VERIFIED: stdlib]` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| rich | >=13 (already a dep) | Progress bar over large walks | Optional (Claude's discretion); already installed. `[VERIFIED: pyproject]` |
| typer | >=0.12 (already a dep) | New `walk`/`inventory` subcommand | If a dedicated subcommand is chosen. `[VERIFIED: pyproject]` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| python-magic | file-magic (freedesktop, currently installed) | **Do NOT use.** Incompatible API (`Magic` class, no `from_buffer`); D-19 mandates python-magic. Both import as `magic`; the wrong one being present is a real hazard (see Pitfall 1). |
| python-magic | Hand-rolled magic-byte table | Don't hand-roll — libmagic has thousands of signatures and is the forensic standard (D-19). |
| Manual recursion via `as_directory()` | TSK C `tsk_fs_dir_walk` callback | pytsk3 does **not** expose the C `dir_walk` callback; manual recursion (open_dir → recurse into DIR entries) is the standard pytsk3 idiom. Confirmed by API surface. |
| `meta`-based content read | Mounting + reading file path | Forbidden (D-05/P1). Always read via the `File` object. |

**Installation:**
```bash
# System (Fedora/RHEL) — libmagic + libtsk already present on this host:
#   sudo dnf install file-libs sleuthkit-devel libewf-devel
# System (Debian/Ubuntu/Kali):
#   sudo apt install libmagic1 libtsk-dev libewf-dev
# Python (add to [project.dependencies] in pyproject.toml):
#   python-magic==0.4.27
```

**Version verification (this session):**
- `pip index versions pytsk3` → latest `20260520`, installed (libtsk reports `4.15.0`). `[VERIFIED]`
- `pip index versions python-magic` → latest `0.4.27`. `[VERIFIED]`
- `pip index versions file-magic` → `0.4.1` (installed 0.4.0) — the WRONG, currently-present binding. `[VERIFIED]`

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| python-magic | PyPI | est. since ~2001, 0.4.27 mature | very high (millions/mo) | github.com/ahupp/python-magic | [OK] (note: "name looks like LLM bait but package is established") | Approved |
| pytsk3 | PyPI | 10+ yrs, dated releases | high (DFIR standard) | github.com/py4n6/pytsk | not re-run (already a Phase 1 dep) | Approved (existing dep) |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
                 evidence image (raw/dd or E01)  ── read-only, never mounted
                              │
                  open_image()  [Phase 1 byte-layer seam: image.py]
                              │  ImageHandle (ReadableImage)
                              ▼
        ┌──────────────────────────────────────────────────────────┐
        │  evidence/filesystem.py  (NEW FS-layer native seam, D-14)  │
        │                                                            │
        │  Volume_Info(img) ──┬─ partitions found ── per-volume ─────┤
        │      │ OSError      │                      offset/desc     │
        │      ▼ (bare FS)    ▼                                      │
        │  fallback offset 0   FS_Info(img, offset=) ── OSError ────►│ (D-20 limitation:
        │                          │ success           (encrypted/    │  record finding,
        │                          ▼                    unsupported)  │  continue walk)
        │                   open_dir("/") ──► recurse via             │
        │                   as_directory() on DIR entries             │
        │                          │                                  │
        │                   yields plain FileEntry value objects ─────┤
        │                   (name, path, alloc/unalloc, addr, type,   │
        │                    size, uid, gid, mode, M/A/C/B epoch+nano,│
        │                    ftype, volume_id/offset, + File reader)  │
        └──────────────────────────────────────────────────────────┘
                              │  FileEntry stream (pure Python)
                              ▼
        ┌──────────────────────────────────────────────────────────┐
        │  core/walk.py  (orchestrator, mirrors core/ingest.py)      │
        │                                                            │
        │   for each FileEntry:                                      │
        │     ├─ normalize MACB → UTC ISO-8601 (timeutil)            │
        │     │     FAT → apply --timezone, flag local-time-inferred │
        │     ├─ if REG & allocated (D-17/D-18):                     │
        │     │     read head bytes → python-magic → file_type       │
        │     │     stream content → MD5/SHA-1/SHA-256 (single pass) │
        │     │     (skip/null if size > --max-hash-size)            │
        │     └─ build FileRow                                       │
        │   batched insert via CaseStore.transaction()              │
        │   audit: walk.start / walk.volume / walk.limitation /     │
        │          walk.end  (REPORT-02)                             │
        └──────────────────────────────────────────────────────────┘
                              │
                              ▼
                  case.db  ── files table + limitation/finding rows
                  (the second source-of-truth feeding Phase 3 timeline)
```

### Recommended Project Structure
```
src/pyautopsy/
├── evidence/
│   ├── image.py          # Phase 1 byte-layer seam (unchanged)
│   ├── integrity.py      # extend: add a 3-digest single-pass helper
│   ├── filesystem.py     # NEW FS-layer native seam (D-14): Volume_Info/FS_Info/Directory/File
│   └── filetype.py       # NEW python-magic wrapper (isolated, testable)
├── core/
│   ├── ingest.py         # Phase 1 (unchanged)
│   └── walk.py           # NEW walk orchestrator (mirrors ingest.py)
├── case/
│   ├── schema.sql        # extend: add `files` table (+ limitation rows)
│   ├── models.py         # add FileRow dataclass
│   └── store.py          # add insert_file / insert_files (bulk) + getters
└── cli/
    └── main.py           # add `walk`/`inventory` subcommand (discretion)
```

### Pattern 1: FS-layer seam yielding plain value objects
**What:** `filesystem.py` is the only new module importing `pytsk3` for the FS layer. It converts native `File`/`Directory`/`meta`/`name` objects into frozen plain-Python `FileEntry` dataclasses (plus a callable byte-reader closure) so no native type escapes the seam — exactly how `image.py` yields `ImageHandle`/`ReadableImage`.
**When to use:** Always — it preserves D-14 and the Phase 1 testability contract.
**Example (API names all empirically verified this session):**
```python
# Source: empirical probe of installed pytsk3 4.15.0 against ext4/NTFS/FAT32 fixtures
import pytsk3

def enumerate_volumes(img: pytsk3.Img_Info):
    """Yield (volume_id, byte_offset, length, desc) per partition; bare FS → one (0,0,...)."""
    try:
        vol = pytsk3.Volume_Info(img)            # mmls equivalent
    except OSError:
        # No partition table (bare filesystem image) → open FS at offset 0 (D-15).
        yield (0, 0, img.get_size(), "bare filesystem (no partition table)")
        return
    for part in vol:
        # part.addr, part.start (in sectors), part.len (sectors), part.desc, part.flags
        yield (part.addr, part.start * vol.info.block_size, part.len * vol.info.block_size,
               part.desc.decode("utf-8", "replace"))

def open_fs(img: pytsk3.Img_Info, offset: int):
    """Open a filesystem; OSError = encrypted/unsupported (D-20 caller records a finding)."""
    return pytsk3.FS_Info(img, offset=offset)    # raises OSError if FS type undetermined
```

### Pattern 2: Recursive directory walk (manual recursion — pytsk3 has no C dir_walk callback)
```python
# Source: empirical probe — as_directory() recursion verified on ext4 fixture
def walk_fs(fs, parent_path="/", _seen=None):
    if _seen is None:
        _seen = set()
    directory = fs.open_dir(path=parent_path)
    for entry in directory:
        name_obj = entry.info.name
        if name_obj is None:
            continue
        name = name_obj.name.decode("utf-8", "replace")
        if name in (".", ".."):
            continue                              # skip self/parent (avoids trivial loops)
        meta = entry.info.meta                    # may be None for some name-only entries
        yield parent_path, name, entry            # caller builds the FileRow
        # Recurse into real directories only; guard against inode revisits (loop/orphan safety).
        if meta is not None and int(meta.type) == int(pytsk3.TSK_FS_META_TYPE_DIR):
            if meta.addr in _seen:
                continue
            _seen.add(meta.addr)
            child_path = parent_path.rstrip("/") + "/" + name
            yield from walk_fs(fs, child_path, _seen)
```
Notes verified empirically:
- `$OrphanFiles` appears as a **virtual directory** (`meta.type == TSK_FS_META_TYPE_VIRT_DIR == 11`) holding recovered orphan-inode entries. It is allocated/visible; recurse into it like a dir if you want its (deleted) children, but **do not** reconstruct orphan trees (Phase 4, D-18).
- Deleted entries appear in the listing with `name.flags`/`meta.flags` UNALLOC set; `meta.addr` is still present.

### Pattern 3: Allocated vs unallocated detection
```python
# Source: empirical probe — flags verified on the deleted ext4 entry
ALLOC_NAME = int(pytsk3.TSK_FS_NAME_FLAG_ALLOC)    # name slot allocated
ALLOC_META = int(pytsk3.TSK_FS_META_FLAG_ALLOC)    # inode/MFT entry allocated
ORPHAN     = int(pytsk3.TSK_FS_META_FLAG_ORPHAN)

name_alloc = bool(int(entry.info.name.flags) & ALLOC_NAME)
meta = entry.info.meta
meta_alloc = bool(meta and int(meta.flags) & ALLOC_META)
is_deleted = not (name_alloc and meta_alloc)       # either slot unallocated ⇒ deleted/unallocated
```

### Pattern 4: MACB → tz-aware UTC ISO-8601 (D-16)
```python
# Source: timeutil.from_epoch_utc (Phase 1) + empirical meta fields
from pyautopsy.util.timeutil import from_epoch_utc, iso_utc

FAT_TYPES = {int(pytsk3.TSK_FS_TYPE_FAT12),
             int(pytsk3.TSK_FS_TYPE_FAT16),
             int(pytsk3.TSK_FS_TYPE_FAT32)}

def macb_iso(meta, ftype: int, walk_tz):  # walk_tz = ZoneInfo from --timezone, default UTC
    """Return {m,a,c,b: ISO-8601-or-None}. FAT epochs are LOCAL; rebase via walk_tz."""
    is_fat = ftype in FAT_TYPES
    def conv(secs, nano=0):
        if not secs:                              # 0 = "not recorded"; emit None, not 1970
            return None
        if is_fat:
            # TSK returns FAT times as epoch assuming a tz; treat the integer as
            # wall-clock-in-walk_tz then express as UTC (flag local-time-inferred).
            from datetime import datetime
            wall = datetime.fromtimestamp(secs, tz=walk_tz)
            return iso_utc(wall)                  # iso_utc converts aware→UTC
        dt = from_epoch_utc(secs)                 # ext4/NTFS already UTC
        # nano fields available as meta.crtime_nano etc. — fold in if sub-second matters
        return iso_utc(dt)
    return {
        "mtime": conv(meta.mtime, getattr(meta, "mtime_nano", 0)),  # Modified
        "atime": conv(meta.atime, getattr(meta, "atime_nano", 0)),  # Accessed
        "ctime": conv(meta.ctime, getattr(meta, "ctime_nano", 0)),  # Changed (metadata)
        "crtime": conv(meta.crtime, getattr(meta, "crtime_nano", 0)),  # Born/created
    }
```
**`timestamp_source` per fs type (D-16):** `f"ext4:inode"`, `f"ntfs:$STANDARD_INFORMATION"`, `f"fat:dir-entry"` — derive from `fs.info.ftype`. For FAT, also set an attribute `"time_precision": "local-time-inferred"` and `"assumed_timezone": str(walk_tz)`. **MACB mapping:** M=mtime, A=atime, C=ctime, B=crtime.

### Pattern 5: Single-pass 3-digest hashing over a TSK File (D-17)
```python
# Source: empirical probe (File.read_random verified) + extend integrity.py D-07 pattern
import hashlib

EMPTY = {  # zero-length sentinel digests (D-17) — verified
    "md5": "d41d8cd98f00b204e9800998ecf8427e",
    "sha1": "da39a3ee5e6b4b0d3255bfef95601890afd80709",
    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
}

def hash_file(tsk_file, size: int, chunk: int = 1 << 20, max_size: int | None = None):
    if size == 0:
        return dict(EMPTY)
    if max_size is not None and size > max_size:
        return None                               # skipped: record null hashes + a reason attr
    md5, sha1, sha256 = hashlib.md5(), hashlib.sha1(), hashlib.sha256()
    off = 0
    while off < size:
        block = tsk_file.read_random(off, min(chunk, size - off))
        if not block:
            break                                  # short read: record partial-read attr, null hashes
        md5.update(block); sha1.update(block); sha256.update(block)
        off += len(block)
    if off != size:
        return None                                # truncated/unreadable — do not record a partial digest
    return {"md5": md5.hexdigest(), "sha1": sha1.hexdigest(), "sha256": sha256.hexdigest()}
```

### Pattern 6: Content-signature typing (D-19, META-05)
```python
# Source: python-magic 0.4.27 from_buffer verified in isolated venv
import magic   # MUST be python-magic, not file-magic — see Pitfall 1
HEAD_BYTES = 4096

def file_type(tsk_file, size: int) -> str | None:
    if size == 0:
        return "inode/x-empty"                     # or None; libmagic-style for empties
    head = tsk_file.read_random(0, min(HEAD_BYTES, size))
    if not head:
        return None
    return magic.from_buffer(head, mime=True)      # e.g. "text/plain", "application/x-sharedlib"
```

### Pattern 7: Encrypted/unsupported volume → known-limitation finding (D-20)
```python
# Source: empirical probe — FS_Info raises OSError "Cannot determine file system type"
for (vol_id, offset, length, desc) in enumerate_volumes(img):
    try:
        fs = open_fs(img, offset)
    except OSError as exc:
        record_limitation(case_store, audit,
            volume_id=vol_id, offset=offset, detected_desc=desc,
            reason=str(exc))                        # "encrypted/unsupported volume"
        continue                                    # walk continues (never empty/garbage)
    walk_and_persist(fs, vol_id, offset)
```
**Cheap encryption hints (optional, MEDIUM confidence):** read the first 512 bytes at the volume offset and check signatures: LUKS magic `b"LUKS\xba\xbe"` at offset 0; BitLocker FVE GUID / `b"-FVE-FS-"` near the NTFS OEM-ID field. These let the finding say "likely LUKS/BitLocker" rather than just "unsupported." Do not attempt decryption (deferred to v2).

### Anti-Patterns to Avoid
- **Importing the wrong `magic`:** assuming `magic.from_buffer` exists without guarding — `file-magic` is currently the installed binding and lacks it (Pitfall 1).
- **`mount`/`losetup`/path-based file reads:** forbidden (D-05/P1). Read only via `File.read_random`.
- **Emitting `1970-01-01` for zero timestamps:** TSK `0` means "not recorded" — emit `None`, never a fake epoch.
- **Treating Volume_Info failure as fatal:** it is the documented bare-FS signal — fall back to offset 0 (D-15).
- **Recursing without an inode-seen guard / `.`/`..` skip:** risks loops on cyclic or malformed directory structures.
- **Hashing directories/symlinks/devices:** gate on `meta.type == REG` (verified: a dir read returns raw dirent bytes, not file content).
- **Naive `datetime.fromtimestamp(secs)` (no tz):** poisons the timeline (P4) — always go through `timeutil`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Filesystem parsing / dir walk / deleted-entry detection | A custom ext4/NTFS/FAT parser | pytsk3 (`FS_Info`, `open_dir`, `as_directory`, flags) | TSK is decades-hardened and court-trusted; reimplementation is a forensic-soundness liability (CLAUDE.md "What NOT to Use"). |
| File-type by content | A magic-byte lookup table | python-magic / libmagic | Thousands of signatures, the forensic standard (D-19). |
| MACB→UTC | Ad-hoc datetime math | `timeutil.from_epoch_utc` + `iso_utc` | The single sanctioned timestamp source (D-10); prevents the P4 naive-datetime class of bug. |
| Multi-digest hashing | Three separate read passes | Extend the D-07 single-pass `hash_image` to 3 digests | One read, three digests — already the project idiom (integrity.py). |
| Bulk DB inserts | Raw SQL in the orchestrator | `CaseStore.transaction()` + new `insert_files` | No raw SQL outside the store; one transaction per batch keeps inserts atomic (WR-01). |

**Key insight:** Phase 2 is almost entirely *composition* of existing primitives — the only genuinely new native surface is the FS seam, and its API is fully verified.

## Runtime State Inventory

> Phase 2 is greenfield-feature work (adds a new module + table), not a rename/refactor. The only "migration-like" concern is a **schema addition**.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — `files` table does not exist yet; `CREATE TABLE IF NOT EXISTS files (...)` is purely additive to `schema.sql`. No existing rows to migrate. | Add table to schema.sql (additive). |
| Live service config | None — no external services. | None. |
| OS-registered state | None. | None. |
| Secrets/env vars | `MTOOLS_SKIP_CHECK=1` is only needed in the **test-fixture build** (mtools quirk), never at runtime. | Set in fixture builder only. |
| Build artifacts | Adding `python-magic` to deps means the package must be reinstalled (`pip install -e .`) for the new import to resolve; `file-magic` should be **uninstalled** from any dev/CI env to avoid the `magic` collision. | Reinstall; document removing file-magic. |

**Existing `case.db` files:** because Phase 2 only adds a table, an old Phase-1 `case.db` opened by the Phase-2 schema will simply gain the `files` table on next `CaseStore.create` (the schema uses `IF NOT EXISTS`). No destructive migration. Verified by reading `schema.sql` + `store.py`.

## Common Pitfalls

### Pitfall 1: `python-magic` vs `file-magic` import collision (HIGH — present on this host)
**What goes wrong:** Both PyPI distributions install a top-level module named `magic`. The host currently has **`file-magic` 0.4.0** installed, whose API is `magic.detect_from_content()` / `magic.Magic()` — it has **no `magic.from_buffer`**. Code written to D-19 (`magic.from_buffer`) will `AttributeError` at runtime if the wrong binding wins the import.
**Why it happens:** They share the import name; pip installs whichever was requested; a dev box can have either.
**How to avoid:**
- Add `python-magic==0.4.27` to `[project.dependencies]`.
- At import time in `filetype.py`, **assert the binding** is python-magic: e.g. `if not hasattr(magic, "from_buffer"): raise ImportError("file-magic detected; install python-magic (the 'magic' module collides)")`. Surface an actionable hint (mirror the PITFALLS P5 pattern used for pyewf in `image.py`).
- Document in README/Containerfile: uninstall `file-magic`, install `python-magic`; the system lib is `libmagic` (Fedora `file-libs`, Debian `libmagic1`).
**Warning signs:** `hasattr(magic, "from_buffer")` is `False`; `magic.__file__` points at a single-file `magic.py` (file-magic) rather than a `magic/` package (python-magic). **Verified this session:** the installed `magic` is file-magic (`/usr/lib/python3.14/site-packages/magic.py`, `from_buffer` absent).

### Pitfall 2: FAT local-time timestamps silently treated as UTC (HIGH, P4)
**What goes wrong:** FAT stores wall-clock local time with no embedded zone; TSK returns it as an epoch int. Treating it as UTC shifts every FAT timestamp by the examiner's/source's offset, poisoning the timeline.
**Why it happens:** ext4/NTFS times *are* UTC, so a single `from_epoch_utc` path looks correct until a FAT volume appears.
**How to avoid:** Branch on `fs.info.ftype` (FAT12/16/32 set); rebase FAT epochs through the `--timezone` zone (default UTC) and flag `local-time-inferred` + `assumed_timezone` in attributes (D-16). Never overclaim precision. **Verified:** FAT32 `atime` came back date-only/midnight-offset distinct from `mtime`, confirming FAT's coarse, local semantics.

### Pitfall 3: Zero TSK timestamps rendered as 1970-01-01
**What goes wrong:** `meta.crtime == 0` on ext2/older or unrecorded fields becomes a fake `1970-01-01T00:00:00Z` event.
**How to avoid:** Treat `0` as "not recorded" → store `None`. (ext4 has crtime; ext2 does not — guard generally.)
**Warning signs:** A cluster of 1970 timestamps in the timeline.

### Pitfall 4: Infinite recursion / re-counting on the directory walk
**What goes wrong:** Following `.`/`..`, cyclic links, or revisiting orphan inodes loops or double-counts.
**How to avoid:** Skip `.`/`..`; track visited `meta.addr` in a seen-set before recursing into a DIR (Pattern 2). Handle `$OrphanFiles` (VIRT_DIR) explicitly.

### Pitfall 5: Hashing/typing non-regular or no-data entries
**What goes wrong:** Calling `read_random` on a directory returns raw dirent bytes (verified), and devices/symlinks have no file content — hashing them is meaningless or errors.
**How to avoid:** Gate content read on `meta is not None and meta.type == TSK_FS_META_TYPE_REG` (D-17). Directories/devices/symlinks → null content hash + null file_type (or a type derived from `meta.type`).

### Pitfall 6: Unsupported-volume open aborting the whole run (D-20)
**What goes wrong:** `FS_Info` raising `OSError` on an encrypted/unsupported volume propagates and kills the walk.
**How to avoid:** Catch `OSError` per volume, record a limitation finding, continue (Pattern 7). **Verified:** `FS_Info` raises `OSError "Unable to open the image as a filesystem ... Cannot determine file system type"`.

### Pitfall 7: `part.start`/`part.len` are in sectors, not bytes
**What goes wrong:** Passing `part.start` directly as a byte offset to `FS_Info` mis-opens the FS.
**How to avoid:** Multiply by the volume block/sector size (`vol.info.block_size`) to get the byte offset (Pattern 1).

## Code Examples

All code in **Architecture Patterns 1–7** above is from this session's empirical probe of installed pytsk3 4.15.0 (against built ext4/NTFS/FAT32 fixtures) and a verified python-magic 0.4.27 venv. Key verified facts:

```python
# meta attributes confirmed present on ext4 + NTFS + FAT32:
meta.addr     # inode (ext4) / MFT record number (NTFS) / dir-entry index (FAT)  → INTEGER
meta.type     # TSK_FS_META_TYPE_REG=1, DIR=2, LNK=6, VIRT_DIR=11
meta.size     # logical size in bytes
meta.uid, meta.gid, meta.mode          # ownership + mode bits (META-03)
meta.mtime, meta.atime, meta.ctime, meta.crtime          # epoch seconds (int)
meta.mtime_nano, meta.atime_nano, meta.ctime_nano, meta.crtime_nano   # sub-second
meta.flags    # TSK_FS_META_FLAG_ALLOC / _UNALLOC / _ORPHAN
entry.info.name.name    # bytes (decode utf-8, errors="replace")
entry.info.name.flags   # TSK_FS_NAME_FLAG_ALLOC / _UNALLOC
fs.info.ftype           # TSK_FS_TYPE_EXT4=8192, NTFS=1, FAT32=8, FAT16=4, FAT12=2
fs.info.block_size, fs.info.root_inum, fs.info.first_inum, fs.info.last_inum
# File access:
f = fs.open(path="/file1.txt")    # or fs.open_meta(inode=N) for deleted-by-addr
f.read_random(offset, size)       # chunked content read (read-only) — verified
fs.open_dir(path="/")             # or fs.open_dir(inode=2)
entry.as_directory()              # recurse into a DIR entry — verified
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| TSK CLI (`fls`/`icat`) + text parsing | Direct pytsk3 structured objects | Long-standing | Project mandate (CLAUDE.md). TSK CLI tools are **NOT installed** on this host; pytsk3 bindings are — confirming the binding-first decision. |
| `wkhtmltopdf` / mount-based reads | Read-only TSK byte access | — | Not Phase 2 concern but reinforces D-05. |

**Deprecated/outdated:** none relevant to Phase 2.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `part.start`/`part.len` are in sectors; multiply by `vol.info.block_size` for byte offset. (Standard TSK semantics; not re-probed on a partitioned image because the bare-FS path is the verified one and partition tables weren't built this session.) | Pattern 1 / Pitfall 7 | FS opens at wrong offset on partitioned images → empty/garbage volume. Plan should add a partitioned-image fixture to verify. |
| A2 | LUKS/BitLocker magic-byte hints are detectable in the first 512 bytes. | Pattern 7 | Only the "likely X" label is affected; the D-20 finding still fires correctly via the `OSError` path. LOW-risk cosmetic. |
| A3 | `meta.*_nano` fields are populated for ext4/NTFS; FAT has none. (`mtime_nano` was 0 on the ext4 fixture — debugfs may not set it; real images differ.) | Pattern 4 | Sub-second precision may be absent; MACB still correct at second granularity. |
| A4 | `$OrphanFiles` (VIRT_DIR) children are deleted-only and should not be tree-reconstructed in Phase 2. | Pattern 2 | If mis-handled, Phase 4's boundary blurs; D-18 explicitly defers this. |

## Open Questions (RESOLVED)

1. **Partitioned-image volume offsets (A1)** — RESOLVED by Wave-0 `build_partitioned_image` fixture + `tests/test_filesystem.py::test_volume_enumeration` (Plans 02-00 / 02-01).
   - What we know: `Volume_Info` enumerates partitions with `.addr/.start/.len/.desc`; bare-FS raises `OSError` (verified).
   - What's unclear: exact byte-offset units on a *real partitioned* image weren't probed this session (only bare-FS ext4/NTFS/FAT32 were built).
   - Recommendation: Wave 0 fixture — build one partitioned disk image (e.g. `parted`/`sfdisk` + a FAT + an ext4 partition) and assert the walk opens both at correct offsets. Treat `part.start * block_size` as the offset.

2. **Path representation for the `files` table (Claude's discretion)** — RESOLVED: store the full-path string AND `parent_addr` (Plan 02-01 Task 1).
   - What we know: full-path string is simplest for Phase 3 timeline display; parent-inode + name is more normalized.
   - Recommendation: store **full path string** (built during recursion) as a typed column AND `parent_addr` for traceability; cheap and serves both consumers.

3. **`file_type` for empty/non-regular entries** — RESOLVED: `inode/x-empty` for empties + `meta_type`-derived labels for non-REG (Plans 02-00 / 02-03).
   - Recommendation: empties → `"inode/x-empty"` (libmagic convention) or `None`; non-regular → derive a simple type string from `meta.type` (e.g. `"directory"`, `"symlink"`), keep `magic`-derived type for REG only.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| pytsk3 | entire walk (META-01..04) | ✓ | 20260520 / libtsk 4.15.0 | — |
| libmagic (system) | content typing (META-05) | ✓ | file-5.46, `/usr/lib64/libmagic.so.1` | — |
| python-magic (PyPI) | `magic.from_buffer` (META-05) | ✗ (file-magic 0.4.0 present instead) | needs 0.4.27 | None — must install; file-magic is API-incompatible (Pitfall 1) |
| mkfs.ext4 + debugfs | ext4 test fixture | ✓ | — | — |
| mkfs.fat + mtools (mcopy) | FAT32 test fixture | ✓ | needs `MTOOLS_SKIP_CHECK=1`, `-F 32`, ≥64MB | — |
| mkntfs (ntfs-3g) | NTFS test fixture | ✓ | — | — |
| TSK CLI tools (fls/mmls/icat) | NOT used (D-14 mandates bindings) | ✗ | — | N/A — bindings used directly |

**Missing dependencies with no fallback:** `python-magic` — **must be added to `[project.dependencies]` and installed**; `file-magic` should be uninstalled from dev/CI to avoid the `magic` collision.
**Missing dependencies with fallback:** none.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (already configured) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`pythonpath=["src"]`, `testpaths=["tests"]`) |
| Quick run command | `python3 -m pytest tests/test_filesystem.py tests/test_walk.py -x` |
| Full suite command | `python3 -m pytest` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| META-01 | Walk inventories every entry incl. a deleted one; alloc/unalloc status + inode addr correct | unit/integration | `pytest tests/test_walk.py::test_inventory_includes_deleted_entry -x` | ❌ Wave 0 |
| META-01 | Bare-FS (offset 0) and (Wave-0) partitioned image both walked; rows tagged volume_id/offset | integration | `pytest tests/test_filesystem.py::test_volume_enumeration -x` | ❌ Wave 0 |
| META-02 | MACB stored as tz-aware UTC ISO-8601 with `+00:00`; FAT flagged `local-time-inferred`; zero→None | unit | `pytest tests/test_walk.py::test_macb_utc_and_fat_flagged -x` | ❌ Wave 0 |
| META-02 | **No naive datetimes anywhere**: every `*time` column parses to an aware datetime; `iso_utc` rejects naive (existing test_timeutil covers the guard) | unit (invariant) | `pytest tests/test_walk.py::test_no_naive_datetimes -x` | ❌ Wave 0 |
| META-03 | uid/gid/mode persisted and match fixture | unit | `pytest tests/test_walk.py::test_ownership_and_mode -x` | ❌ Wave 0 |
| META-04 | MD5+SHA1+SHA256 per regular file match a direct hashlib pass; empty file → sentinel digests; `--max-hash-size` skips + records reason | unit | `pytest tests/test_walk.py::test_three_digest_single_pass -x` | ❌ Wave 0 |
| META-05 | `file_type` derived from content (text file typed text/plain even with misleading extension) | unit | `pytest tests/test_walk.py::test_filetype_by_content_not_extension -x` | ❌ Wave 0 |
| D-20 | Unsupported/garbage-offset volume → limitation finding row, walk continues, no empty/garbage file rows | integration | `pytest tests/test_walk.py::test_unsupported_volume_records_limitation -x` | ❌ Wave 0 |
| D-14 | Seam allowlist: no `pytsk3` import outside `evidence/image.py` + `evidence/filesystem.py` | unit (arch guard) | `pytest tests/test_seam_allowlist.py -x` | ❌ Wave 0 |
| D-05/P1 | Walk never mounts/writes source (mtime+size unchanged after walk) | integration | `pytest tests/test_readonly_guarantee.py::test_source_unchanged_after_walk -x` | ❌ Wave 0 |

### Sampling Rate
- **"Every file" coverage signal:** the walk must yield a **count equal to** an independent ground-truth count for each fixture (e.g. number of entries created + the known deleted entry + expected system files for NTFS). Assert exact expected row counts per fixture rather than spot-checking — the Nyquist signal that "every file" was inventoried.
- **Per task commit:** `pytest tests/test_filesystem.py tests/test_walk.py -x` (fast; tiny fixtures).
- **Per wave merge:** `python3 -m pytest` (full suite).
- **Phase gate:** full suite green before `/gsd-verify-work`.

### "No naive datetimes" invariant (success-criterion 2)
- The single sanctioned serializer `iso_utc` **already rejects naive datetimes** (verified in `timeutil.py`) — route every MACB value through it, making naive values impossible to persist.
- Add a test that reads back every `files` MACB column and asserts each non-null value ends with an explicit offset (`+00:00`) and re-parses to an aware datetime.

### Wave 0 Gaps
- [ ] `tests/fixtures/make_fixtures.py` — add `build_tiny_ext4_image` (mkfs.ext4 `-F` + debugfs write/rm for a deleted entry), `build_tiny_fat32_image` (`mkfs.fat -F 32`, ≥64MB, `MTOOLS_SKIP_CHECK=1 mcopy`), `build_tiny_ntfs_image` (`mkntfs -F -Q`), and a `build_partitioned_image` (parted/sfdisk + 2 FS) for the volume-offset test. Commit the built images (they're tiny) to keep CI mkfs-free, mirroring the existing `tiny_raw.dd` approach.
- [ ] `tests/test_filesystem.py` — seam-level tests: volume enumeration, bare-FS fallback, FS-type detection, `OSError`→limitation, recursion correctness.
- [ ] `tests/test_walk.py` — orchestrator tests covering META-01..05 + D-20 (table above).
- [ ] `tests/test_seam_allowlist.py` — arch guard: scan `src/` for `import pytsk3` / `import pyewf` and assert only the D-14 allowlist files contain them (this gate is currently a *convention*, not an automated test — Phase 2 should make it executable).
- [ ] `tests/test_readonly_guarantee.py` — extend with `test_source_unchanged_after_walk`.
- [ ] Framework install: add `python-magic==0.4.27` to deps; `pip install -e .`; ensure `file-magic` is absent in the test env.

## Security Domain

> `security_enforcement: true`, ASVS level 1.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth surface in a local CLI. |
| V3 Session Management | no | — |
| V4 Access Control | yes | Read-only evidence boundary (D-05/P1): walk reads only via `File.read_random`; `assert_source_not_mounted` already guards (reuse). No write/mount path. |
| V5 Input Validation | yes | The disk image is **untrusted input**. Decode names with `errors="replace"`; bound recursion (seen-set); never `eval`/path-execute names; treat extracted names as data only. `--timezone` validated via `zoneinfo.ZoneInfo` (raises on bad zone). |
| V6 Cryptography | yes | Hashes are integrity/identification, not security. `hashlib` only; SHA-256 primary, MD5/SHA-1 for hash-set interop (never as tamper-evidence) — consistent with Phase 1. |

### Known Threat Patterns for {pytsk3 walk of untrusted images}
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Malicious directory cycle / deep nesting (DoS) | Denial of Service | Inode seen-set + skip `.`/`..` (Pattern 2); optional depth cap. |
| Crafted huge logical size to exhaust hashing time/memory | Denial of Service | `--max-hash-size` (D-17); streaming chunked reads (memory-bounded). |
| Hostile filenames (path traversal, control chars, non-UTF-8) | Tampering | Names are stored as **data only**, never used as filesystem paths to write; decode with `errors="replace"`. Output is confined to `case.db` (no extraction in Phase 2). |
| Encrypted/unsupported volume crashing the run | Availability/Integrity | D-20 catch-and-record; walk continues (Pattern 7). |
| Writing/altering the evidence source | Tampering | Read-only TSK access; reuse `assert_source_not_mounted`; never mount (D-05/P1). |

## Sources

### Primary (HIGH confidence)
- **Empirical probe (this session)** — installed `pytsk3` 4.15.0 against purpose-built ext4 (`mkfs.ext4`+`debugfs`), NTFS (`mkntfs`), and FAT32 (`mkfs.fat`+`mcopy`) fixtures: verified `Volume_Info` (raises `OSError` on bare FS), `FS_Info(offset=)` (raises `OSError` on undetermined FS), `open_dir`/`as_directory`, `meta.addr/type/size/uid/gid/mode/mtime/atime/ctime/crtime/*_nano/flags`, `name.name/.flags`, `fs.info.ftype/block_size`, `File.read_random`, `open_meta(inode=)`, deleted-entry visibility + `$OrphanFiles` VIRT_DIR.
- **Empirical probe** — `python-magic` 0.4.27 in an isolated venv: `magic.from_buffer(buf, mime=True)` returns `text/plain` / `application/x-sharedlib`. Confirmed the host's installed `magic` is **file-magic** (no `from_buffer`).
- **Project source** — `evidence/image.py`, `evidence/integrity.py`, `core/ingest.py`, `case/store.py`, `case/schema.sql`, `case/models.py`, `util/timeutil.py`, `cli/main.py` (read this session).
- **PyPI** — `pytsk3` 20260520, `python-magic` 0.4.27, `file-magic` 0.4.1 (via `pip index versions`).
- **slopcheck** — `python-magic` rated `[OK]`.

### Secondary (MEDIUM confidence)
- `.planning/research/STACK.md`, `PITFALLS.md`, `ARCHITECTURE.md` — project research (pytsk3 walk API, P1/P3/P4 pitfalls, blackboard schema).
- CLAUDE.md tech-stack guidance (pytsk3 direct; never wrap Autopsy; never mount).

### Tertiary (LOW confidence)
- LUKS/BitLocker magic-byte hints (A2) — training knowledge, not probed this session.
- Partition byte-offset = `part.start * block_size` (A1) — standard TSK semantics, not probed on a partitioned image this session.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — pytsk3 API + python-magic API empirically verified against real fixtures.
- Architecture: HIGH — mirrors the proven Phase 1 seam/orchestrator/store layering.
- Pitfalls: HIGH — the magic-binding collision, FAT local-time, and FS_Info-raises behaviors were all directly observed this session.
- Test fixtures: HIGH — all three filesystem builders (+ exact flags/sizes) were run successfully without root.
- Partitioned-volume offsets: MEDIUM — bare-FS verified; partitioned path is A1 (Wave-0 fixture recommended).

**Research date:** 2026-05-31
**Valid until:** 2026-06-30 (stable, mature stack; pytsk3/libmagic move slowly)
