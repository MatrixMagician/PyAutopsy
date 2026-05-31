---
phase: 02-filesystem-walk-metadata
plan: 03
subsystem: evidence-integrity + walk-orchestrator
tags: [hashing, content-typing, META-04, META-05, D-17, D-19]
requires:
  - "02-02: walk.py orchestrator + FileRow row build"
  - "02-01: filesystem.py FS-layer seam (FileEntry.read_random)"
  - "Phase-1 integrity.py hash_image single-pass idiom (D-07)"
  - "Wave-0 filetype.py libmagic wrapper + binding-collision guard"
provides:
  - "integrity.hash_file: single-pass MD5+SHA-1+SHA-256 per file + EMPTY sentinel + size cap"
  - "walk.py: md5/sha1/sha256 + file_type populated for allocated regular files"
  - "filesystem.py: name-type fallback so debugfs/recovered regular files label 'reg'"
affects:
  - "Phase 4 known-file filtering (hashes are the join key)"
  - "Phase 3 report (file_type + integrity columns)"
tech-stack:
  added: []
  patterns:
    - "Single-pass multi-digest streaming (one read loop, three hashers)"
    - "Injectable typer (FileTyper) keeps the orchestrator testable with a fake"
    - "Plain Callable type aliases (not Protocols) so positional-only seam closures match"
key-files:
  created: []
  modified:
    - "src/pyautopsy/evidence/integrity.py"
    - "src/pyautopsy/core/walk.py"
    - "src/pyautopsy/evidence/filesystem.py"
    - "src/pyautopsy/evidence/filetype.py"
    - "tests/test_walk.py"
decisions:
  - "Hash only allocated regular files; non-regular entries get null hashes + an optional structural type label, never a magic call on dirent bytes (Pitfall 5)"
  - "Per-file short read returns None (skip + reason), diverging from hash_image which raises — one unreadable entry must not abort the whole inventory"
  - "Derive meta-type from the dir-entry name.type when the inode meta.type is UNDEF (mirrors TSK fls); without this every debugfs-written fixture file was mislabelled 'unknown' and left unhashed"
metrics:
  duration: "~25m"
  completed: "2026-05-31"
  tasks: 2
  files_changed: 5
  commits: 3
---

# Phase 2 Plan 03: Per-File Hashing + Content-Signature Typing Summary

The final Phase 2 enrichment slice: every allocated regular file now carries
MD5 + SHA-1 + SHA-256 (computed in a single streaming pass) and a content-derived
MIME `file_type`, both read read-only through the FS seam's `read_random` closure
— never by extension, never by mounting.

## What Was Built

**Task 1 — `integrity.hash_file` (META-04, D-17).** Extended `integrity.py` (not
a new module) with `hash_file(read_random, size, *, chunk=1MiB, max_size=None)`,
reusing the Phase-1 `hash_image` single-pass shape: one `while off < size` loop
updates `md5`, `sha1`, and `sha256` together. Added a module-level `EMPTY`
sentinel dict (the well-known zero-byte digests) returned for size-0 files. A
file over `max_size` returns `None` (DoS guard, T-2-03-HOG); a short/truncated
read returns `None` (no partial digest, preserving D-08's principle); `chunk <= 0`
raises `ValueError`. Stays native-free (no `pytsk3`).

**Task 2 — Wire hashing + typing into the walk (META-04, META-05).** `walk.py`'s
per-entry row build now calls `_content_fields`, which gates content work on an
allocated regular file with a readable `read_random` closure: it streams
`hash_file` into `md5/sha1/sha256` (or records `attributes["hash_skipped"]` =
`exceeds_max_hash_size` / `short_read` with null hashes), and calls the injected
`file_type` typer for the content MIME. Non-regular entries get null hashes and
only an optional structural label (`directory`/`symlink`) — libmagic is never run
on dirent bytes (Pitfall 5, T-2-03-NONREG). `max_hash_size` is threaded through
`_build_file_row`; the typer is injectable (defaults to `filetype.file_type`) so
the orchestrator stays unit-testable.

## Verification

- `pytest` full suite: **145 passed, 0 RED** (phase gate). The two long-standing
  RED stubs (`test_three_digest_single_pass`, `test_filetype_by_content_not_extension`)
  are now GREEN with real bodies.
- Seam allowlist GREEN; `grep -Ec '^\s*(import|from)\s+pytsk3'` on
  `walk.py` / `integrity.py` / `filetype.py` is `0` each (D-14 preserved).
- `test_source_unchanged_after_walk` GREEN: content reads did not alter the
  source mtime/size (D-05/P1 read-only guarantee intact).
- `ruff check` and `mypy` clean on all four touched source files.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Meta-type mislabelled 'unknown' for debugfs/recovered regular files**
- **Found during:** Task 2 (the e2e walk assertions returned `md5 == None`,
  `file_type == None` for the known `file1.txt`).
- **Issue:** `filesystem.walk_fs` derived `meta_type` solely from the inode's
  `meta.type`. The ext4 fixture's `file1.txt` (written by `debugfs`) carries
  `meta.type == TSK_FS_META_TYPE_UNDEF (0)` while its directory entry correctly
  records `name.type == TSK_FS_NAME_TYPE_REG (5)`. The label therefore fell back
  to `"unknown"`, so the `meta_type == "reg"` content gate excluded a genuine
  regular file — every fixture file would have been left unhashed/untyped.
- **Fix:** Added `_NAME_TYPE_LABELS` (the distinct `TSK_FS_NAME_TYPE_*` enum
  space) and a name-type fallback in `_meta_type_label`: when `meta.type` is
  absent/unmapped, fall back to the dir-entry `name.type`. This mirrors TSK's own
  `fls` behaviour. Directory recursion still keys off the integer `meta.type`, so
  the fix is purely on the label.
- **Files modified:** `src/pyautopsy/evidence/filesystem.py` (an allowlisted seam).
- **Commit:** 5625cf4

**2. [Rule 3 - Blocking] Reader Protocols rejected positional-only seam closures (mypy)**
- **Found during:** Task 2 type-check.
- **Issue:** `integrity.ContentReader` and `filetype.HeadReader` were `Protocol`s
  with a keyword-capable `__call__`; the FS seam's `read_random` closure is a
  positional-only `Callable[[int, int], bytes]`, which mypy reports as a
  structural mismatch (and the contravariant typer-default assignment failed too).
- **Fix:** Replaced both Protocols with plain `Callable[[int, int], bytes]` type
  aliases. Identical runtime behaviour; the seam closure now matches structurally
  and `mypy` is clean.
- **Files modified:** `src/pyautopsy/evidence/integrity.py`,
  `src/pyautopsy/evidence/filetype.py`.
- **Commit:** 5625cf4

## Known Stubs

None. The two former `pytest.fail` stubs are now implemented and GREEN.

## Self-Check: PASSED

- `src/pyautopsy/evidence/integrity.py` — FOUND, `def hash_file` present, `sha1` present.
- `src/pyautopsy/core/walk.py` — FOUND, `file_type` populated, `hash_file` call present.
- `src/pyautopsy/evidence/filesystem.py` — FOUND, name-type fallback present.
- Commits 311500c (test), 9d2c0c1 (hash_file), 5625cf4 (wire) — all present in git log.
- Full suite 145 passed / 0 RED; seam invariant 0/0/0.
