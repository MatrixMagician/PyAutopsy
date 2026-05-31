---
phase: 02-filesystem-walk-metadata
reviewed: 2026-05-31T00:00:00Z
depth: deep
files_reviewed: 14
files_reviewed_list:
  - src/pyautopsy/case/models.py
  - src/pyautopsy/case/schema.sql
  - src/pyautopsy/case/store.py
  - src/pyautopsy/cli/main.py
  - src/pyautopsy/core/walk.py
  - src/pyautopsy/evidence/filesystem.py
  - src/pyautopsy/evidence/filetype.py
  - src/pyautopsy/evidence/integrity.py
  - tests/conftest.py
  - tests/fixtures/make_fixtures.py
  - tests/test_filesystem.py
  - tests/test_readonly_guarantee.py
  - tests/test_seam_allowlist.py
  - tests/test_walk.py
findings:
  critical: 2
  warning: 6
  info: 4
  total: 12
status: resolved
resolution: All 2 Critical + 6 Warning + 3 Info findings fixed in commits 7db73c9, 530b055, 8956bbc, 7581425, 40c3ffc, ef34062 (155 tests green). IN-03 (cosmetic) skipped.
---

# Phase 2: Code Review Report

**Reviewed:** 2026-05-31
**Depth:** deep
**Files Reviewed:** 14
**Status:** issues_found

## Summary

Phase 2 adds the filesystem-walk tier: an FS-layer pytsk3 seam
(`evidence/filesystem.py`), a content-typing module (`filetype.py`), per-file
single-pass hashing (`integrity.hash_file`), and the `run_walk` orchestrator that
turns an opened image into a per-file inventory. The architecture invariants hold
well: native bindings (`pytsk3`/`pyewf`) are confined to the two-module D-14
allowlist; `import magic` is guarded by the `from_buffer` binding-collision check
(D-19); no mount/write path to the source exists; the seam yields only frozen
plain-Python value objects; and `iso_utc` structurally rejects naive datetimes.

However, the adversarial pass surfaced two correctness defects that the committed
fixtures and tests do **not** catch because the tests assert only structural
properties (ISO suffix, flags present) rather than the actual values, and because
every committed filesystem fixture happens to be ext4/FAT32 — never ext2/ext3.
Both defects produce **silently wrong forensic output** rather than crashes,
which is the most dangerous failure mode for an evidence tool.

## Critical Issues

### CR-01: FAT local-time rebasing is a no-op — FAT MACB timestamps are wrong by the zone offset

**File:** `src/pyautopsy/core/walk.py:128-136` (`_macb_to_utc_iso`)
**Issue:**
The FAT branch is intended to take a wall-clock-in-`walk_tz` value and convert it
to true UTC (the whole point of `--timezone` and the `local-time-inferred` flag,
D-16, threat T-2-02-FAT). It does:

```python
if is_fat:
    dt = datetime.fromtimestamp(secs, tz=walk_tz)   # <-- bug
else:
    dt = from_epoch_utc(secs)
...
return iso_utc(dt)   # astimezone(UTC).isoformat()
```

`datetime.fromtimestamp(secs, tz=walk_tz)` interprets `secs` as a **UTC epoch**
and merely *renders* it in `walk_tz`; the absolute instant is identical to the
non-FAT `from_epoch_utc(secs)` path. `iso_utc` then converts back to UTC,
yielding exactly the same UTC value as if no rebasing happened. Verified:

```
secs=1700000000, tz=America/New_York
 fromtimestamp(secs, tz=NY)      -> 2023-11-14 22:13:20+00:00   (code's result)
 reinterpret-wall-clock-as-local -> 2023-11-15 03:13:20+00:00   (correct result)
```

So FAT timestamps are stored 5 hours (one UTC offset) off the true instant, while
the row is *labelled* `local-time-inferred` / `assumed_timezone=America/New_York`
— i.e. the report actively claims a rebasing that did not occur. This poisons the
FAT timeline (PITFALLS Pitfall 2). `test_macb_utc_and_fat_flagged` does not catch
it because it asserts only `mtime_utc.endswith("+00:00")` and the flag fields, not
the converted value.

**Fix:** TSK reports FAT wall-clock fields as a UTC epoch (when opened without a
zone). Reinterpret those wall-clock fields as being in `walk_tz`, then convert:
```python
if is_fat:
    # secs are wall-clock fields TSK encoded as if UTC; reinterpret in walk_tz.
    naive_wall = datetime.fromtimestamp(secs, tz=timezone.utc).replace(tzinfo=None)
    dt = naive_wall.replace(tzinfo=walk_tz)
else:
    dt = from_epoch_utc(secs)
```
Add a value-level assertion to `test_macb_utc_and_fat_flagged` (e.g. compare the
FAT UTC result against the known fixture wall-clock minus the NY offset) so the
no-op cannot regress silently.

### CR-02: ext2/ext3 filesystems are mislabelled `unknown`; `_EXT_FTYPES` holds the wrong enum values

**File:** `src/pyautopsy/core/walk.py:78-90` (`_EXT_FTYPES`, `_fs_type_label`)
**Issue:**
`_EXT_FTYPES = frozenset({2, 4, 8})` is commented "libtsk EXT2/EXT3/EXT4 enum
group", but those integers are actually the **FAT** enum values
(`TSK_FS_TYPE_FAT12=2`, `FAT16=4`, `FAT32=8`). The real ext values are
`EXT2=128`, `EXT3=256`, `EXT4=8192`. Verified against installed pytsk3 4.15.0.

Consequences:
- The `_EXT_FTYPES` membership test is dead/misleading: `{2,4,8}` is already
  fully shadowed by `FAT_FS_TYPES` (which is checked first), so it never
  classifies anything as `ext` and can never fire on a real ext fs.
- Only `_EXT4_FTYPE == 8192` is correct, so **ext4 works by accident**. An
  **ext2 (128) or ext3 (256)** image falls through to `return "unknown"`:
  `fs_type` column = `"unknown"`, `timestamp_source` = `None` (the
  `_TIMESTAMP_SOURCE_BY_LABEL` lookup misses), and the FAT/ext branching is lost.
  This is invisible today only because every committed fixture is ext4/FAT32.

**Fix:**
```python
_NTFS_FTYPE = int(...)  # prefer deriving from the seam, not magic ints
_EXT_FTYPES = frozenset({128, 256, 8192})  # EXT2 / EXT3 / EXT4

def _fs_type_label(fs_ftype: int) -> str:
    if fs_ftype in FAT_FS_TYPES:
        return "fat"
    if fs_ftype == _NTFS_FTYPE:
        return "ntfs"
    if fs_ftype in _EXT_FTYPES:
        return "ext"
    return "unknown"
```
Better: export an `EXT_FS_TYPES`/`NTFS_FS_TYPES` frozenset from
`evidence/filesystem.py` derived from the pytsk3 enums (same pytsk3-free contract
already used for `FAT_FS_TYPES`) so these labels can never drift from the binding
again. Add an ext2 or ext3 fixture (or at least a unit test feeding `fs_ftype=128`
/ `256` to `_fs_type_label`) to lock the mapping.

## Warnings

### WR-01: A single unreadable entry aborts the whole walk, defeating the D-20 "continue" intent

**File:** `src/pyautopsy/core/walk.py:266-297` (`_content_fields`), `474-486`
**Issue:**
`_content_fields` calls `integrity.hash_file(reader, ...)` and `typer(reader, ...)`
with **no try/except** around the `read_random` content reads. The only `OSError`
guard is at the *volume* level (`open_fs`, line 447-449). If reading one
deleted/corrupt entry's content raises `OSError`/`IOError` (a common case for
unallocated files whose data runs are gone), the exception propagates out of
`_build_file_row` → the per-volume loop → the broad `except Exception` at line
508, writes a `walk.error` FAIL event, and **aborts the entire inventory**. The
careful per-file short-read→`None` resilience in `hash_file` is bypassed because
the read raises before returning. One unreadable entry should not destroy the
whole run (the spirit of D-20 / Pitfall 6).
**Fix:** Wrap the content read so a read failure degrades to null hashes/type +
a `read_error` attribute and continues:
```python
try:
    digests = integrity.hash_file(reader, entry.size, max_size=max_hash_size)
except OSError as exc:
    attributes["hash_skipped"] = "read_error"
    digests = None
...
try:
    file_type = typer(reader, entry.size)
except OSError:
    file_type = None
```

### WR-02: Deleted/unallocated regular files are content-typed without a provenance caveat

**File:** `src/pyautopsy/core/walk.py:278-296`
**Issue:**
Hashing is correctly gated on `if entry.allocated:` (D-18 — do not hash reclaimed
blocks as if intact). But `file_type = typer(reader, entry.size)` at line 296 runs
**unconditionally for every regular entry**, including unallocated/deleted ones.
libmagic is therefore fed the leading bytes of a deleted file whose blocks may
have been reused by another file, and the resulting `file_type` is recorded with
no flag distinguishing it from an allocated-file type. This is the same
forensic-soundness hazard the hashing guard was written to avoid, just on the
typing column.
**Fix:** Either gate typing on `entry.allocated` too, or (preferred — typing a
deleted file is still useful) record a caveat when typing an unallocated entry:
```python
if not entry.allocated:
    attributes["file_type_provenance"] = "unallocated-blocks-may-be-reused"
```

### WR-03: `parent_addr` is always `None` despite being plumbed end-to-end

**File:** `src/pyautopsy/evidence/filesystem.py:358`
**Issue:**
`FileEntry.parent_addr` is hardcoded to `None` in `walk_fs`, and the value flows
unchanged through `_build_file_row` → `FileRow.parent_addr` → the `files.parent_addr`
column. The column, model field, and store round-trip all exist (META-01 says
"when known"), and the parent inode *is* knowable during recursion — `walk_fs`
already holds the parent directory's `parent_path` and could carry the parent's
`meta.addr` into the recursive call. As written the column is dead: every row's
`parent_addr` is null, so no parent/child reconstruction is possible downstream.
**Fix:** Thread the parent inode address into the recursion and set it:
```python
def walk_fs(fs, volume_id, volume_offset, parent_path="/", parent_addr=None, _seen=None):
    ...
    yield FileEntry(..., parent_addr=parent_addr, ...)
    ...
    yield from walk_fs(fs, volume_id, volume_offset, child_path, meta_addr, _seen)
```

### WR-04: `walk_fs` recurses by path, so a cycle/hardlink can be re-opened before the inode guard fires

**File:** `src/pyautopsy/evidence/filesystem.py:332`, `382-391`
**Issue:**
The seen-set guard (`if meta.addr in _seen`) correctly prevents re-*recursing* a
known inode, but recursion re-opens each child via `fs.open_dir(path=child_path)`
(by path string), and `_seen` only tracks directory inodes that were *entered*.
A directory hardlinked under two different names at the same level (rare but
constructible, and present in some NTFS/`$OrphanFiles` shapes) yields two distinct
`child_path`s pointing at the same inode; the first enters and adds the inode, the
second is then guarded — correct — but the *entries themselves* are still emitted
twice with different paths, inflating counts. More importantly, deep adversarial
nesting recurses with Python's call stack (no depth cap): a crafted image with
thousands of nested dirs raises `RecursionError`, again caught by the broad
`except Exception` and aborting the walk.
**Fix:** Add an explicit depth cap (or convert to an iterative work-list) and
de-duplicate emitted entries by `(meta_addr, name)` if path-based double-emission
is a concern. At minimum, document the recursion-depth assumption.

### WR-05: Broad `except Exception` swallows programming errors into a generic FAIL

**File:** `src/pyautopsy/core/walk.py:508`
**Issue:**
`except Exception as exc:` catches *everything* (including `KeyError`,
`AttributeError`, `TypeError` from genuine bugs) and re-raises after writing a
`walk.error` audit event with `error_type`. While the re-raise preserves the
traceback, the breadth means a latent programming bug is reported identically to
an expected operational failure, and combined with WR-01 it converts recoverable
per-entry conditions into whole-run aborts. Narrow to the operational exception
set actually expected (`OSError`, `sqlite3.Error`, `IntegrityError`,
`MountedSourceError`, `WalkError`) and let true bugs surface unwrapped, or keep the
broad catch only as a last-resort audit wrapper that re-raises (current behaviour)
but pair it with the WR-01 per-entry guard so it is not the primary control path.
**Fix:** Tighten the caught set, or add per-entry guards (WR-01) so this remains a
last-resort wrapper rather than the routine failure path.

### WR-06: `FileRow.volume_id`/`volume_offset` typed non-optional but read from nullable columns

**File:** `src/pyautopsy/case/models.py:125-126`; `src/pyautopsy/case/store.py:383-384`; `src/pyautopsy/case/schema.sql:66-67`
**Issue:**
`schema.sql` declares `volume_id INTEGER` and `volume_offset INTEGER` (both
NULL-able), and `get_file` assigns `row["volume_id"]` / `row["volume_offset"]`
straight into `FileRow`, whose annotations are non-optional `int`. A row inserted
elsewhere with NULL `volume_id` would silently construct a `FileRow` with `None`
in an `int` field (frozen dataclass does no validation), violating the declared
type and breaking any consumer that does integer math on it. Today the walk always
sets both, so it does not bite, but the contract is inconsistent.
**Fix:** Either make the schema columns `NOT NULL` (the walk always provides
them) or change the model annotations to `int | None` and reflect that in the
`get_file` reconstruction.

## Info

### IN-01: `integrity.py` module docstring understates the digests it computes

**File:** `src/pyautopsy/evidence/integrity.py:3-4`
**Issue:** The header says the module "streams **MD5 + SHA-256** in a single
pass", but `hash_file` computes MD5 + SHA-1 + SHA-256. Misleading for maintainers.
**Fix:** Update the docstring to note `hash_file` adds SHA-1 (NSRL/legacy interop).

### IN-02: `_unescape_mount_field` decodes with `surrogateescape` but its docstring claims UTF-8

**File:** `src/pyautopsy/evidence/integrity.py:367-369`
**Issue:** The docstring/module comment says the field is decoded "as UTF-8", but
the code uses `errors="surrogateescape"`. Functionally fine (and arguably safer),
but the stated contract and the code disagree.
**Fix:** Align the comment with the actual `surrogateescape` behaviour.

### IN-03: `EXT4_DELETED_NAME` constant unused; deleted fixture filename hardcoded in the debugfs script

**File:** `tests/fixtures/make_fixtures.py:170-171`
**Issue:** The script writes `deleted` as `EXT4_DELETED_NAME` (good) but the
`live`/`deleted` temp filenames and `sif` lines duplicate `FS_FILE_NAME`
references; low-risk drift if either constant changes. Minor.
**Fix:** Optional — derive all script names from the constants only.

### IN-04: `_macb_to_utc_iso` can raise `OSError`/`OverflowError` on an out-of-range epoch

**File:** `src/pyautopsy/core/walk.py:130`, `133`
**Issue:** A crafted/garbage `secs` (very large, or platform-dependent negative)
passed to `datetime.fromtimestamp` can raise `OverflowError`/`OSError`, which
(via WR-01/WR-05) would abort the walk. Low likelihood given TSK-sourced ints, but
unguarded.
**Fix:** Clamp/validate the epoch range, or catch and map to `None` with a
`timestamp_out_of_range` attribute.

---

_Reviewed: 2026-05-31_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
