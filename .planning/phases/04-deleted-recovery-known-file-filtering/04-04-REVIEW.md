---
phase: 04-deleted-recovery-known-file-filtering
reviewed: 2026-05-31T00:00:00Z
depth: deep
files_reviewed: 5
files_reviewed_list:
  - src/pyautopsy/evidence/filesystem.py
  - tests/fixtures/fake_fs.py
  - tests/fixtures/make_fixtures.py
  - tests/test_filesystem.py
  - tests/test_recover.py
findings:
  critical: 0
  warning: 2
  info: 2
  total: 4
status: issues_found
---

# Phase 4: Code Review Report (RECOV-02 gap-closure, plan 04-04)

**Reviewed:** 2026-05-31
**Depth:** deep (cross-file: seam → orchestrator → tests, plus live fixture probing)
**Files Reviewed:** 5
**Status:** issues_found

## Summary

Focused adversarial review of the RECOV-02 root-level deleted-file
misclassification fix (commits 63123a0..a96cfd5). The ~20-line production change
in `walk_fs` substitutes `int(fs.info.root_inum)` for the root call's `None`
`parent_addr`, so a root-level deletion carries an *allocated* parent and
classifies `is_orphan=False` (Recovered) instead of being falsely flagged orphan.

I verified the change against the live committed fixtures with `pytsk3 4.15.0`
(the source tree, `PYTHONPATH=src`):

- **ext4 root deletion** (`deleted.txt`, inode 13): `parent_addr=2`,
  `is_orphan=False` — Recovered. Correct.
- **FAT root deletion** (inode 4): `parent_addr=2`, `is_orphan=False` —
  Recovered. Correct.
- **Genuine orphan** (`ext4_orphan.img`, inode 13, parent dir removed):
  `parent_addr=12` (an *unallocated* inode reached via the `$OrphanFiles` walk),
  `is_orphan=True` — still Orphan. The fix does NOT swallow the genuine orphan.

All four design invariants in the scope note hold:

- **Root-inode tagging correctness.** The `_depth == 0 and parent_addr is None`
  guard fires only on the genuine top-level call; the recursive call always
  passes a non-`None` child `meta_addr`, so `None` stays reserved exclusively for
  the pass-2 range-scan orphan. The orphan disambiguation depends on
  `root_inum ∈ allocated_inodes(fs)`, which I confirmed empirically for ext4
  (root 2, range [1,129]), FAT (root 2, range [2,2064358]) and NTFS (root 5,
  range [0,65]). See WR-01 for the unguarded `first_inum > root_inum` corner.
- **D-14 native seam.** `import pytsk3` appears only in `evidence/image.py` and
  `evidence/filesystem.py`; the fix introduced no new importer
  (`core/recover.py` and all orchestrator/test tiers stay pytsk3-free).
- **Forensic soundness.** No write/mount/`truncate`/`unlink` path exists in the
  seam (only docstring/comment mentions of "read-only"); recovery never overclaims
  — orphan-ness is a provenance fact OR'd from `di.is_orphan`/`entry.is_orphan`,
  and the tier copy is honesty-scanned. `parent_addr` is now a stable `int`
  (deterministic), preserving CLI-02 report-body byte-determinism.
- **Test quality (both directions, fails on revert).** I simulated a revert
  (dropped the `root_inum` substitution); `test_root_entries_carry_root_inode_parent_addr`,
  `test_root_level_deletion_is_not_orphan`, and
  `test_parent_addr_threaded_through_recursion` all fail. The genuine-orphan
  direction is pinned by `test_removed_parent_deletion_is_still_orphan`. Full
  suite: `tests/test_filesystem.py` 13 passed, `tests/test_recover.py` 6 passed.

No blocking defects. Two robustness warnings and two info items below.

> **Environment note (not a code defect):** a stale, non-editable
> `pyautopsy` is installed in `~/.local/lib/python3.14/site-packages` that
> predates the fix. Importing without `PYTHONPATH=src` exercises that stale copy
> and shows the *old* (buggy) behaviour. The test suite is insulated via
> `pyproject.toml [tool.pytest.ini_options] pythonpath = ["src"]`, so CI is
> correct — but a developer running an ad-hoc REPL/script can silently hit the
> "tested the wrong copy" trap. Flagged as IN-02.

## Warnings

### WR-01: Root-inode tagging silently breaks if a filesystem reports `first_inum > root_inum`

**File:** `src/pyautopsy/evidence/filesystem.py:421-434` (`allocated_inodes`) in
conjunction with `:724-725` (root substitution) and `:474-475` (orphan check).

**Issue:** The fix's correctness is transitively conditional on the root inode
being inside the allocated-inode scan range. `walk_fs` tags root entries with
`int(fs.info.root_inum)`, and `iter_deleted_inodes` classifies a root-level
deletion non-orphan only because `root_inum ∈ alloc_inodes`. But
`allocated_inodes` scans exactly `range(first_inum, last_inum + 1)`. If any
filesystem (now or a future TSK back-end) reports `first_inum > root_inum`, the
root inode is never visited, `root_inum ∉ alloc_inodes`, and the orphan check
`fe.parent_addr not in alloc_inodes` becomes `True` — re-introducing the exact
RECOV-02 false-orphan bug for *every* root-level deletion, silently. The three
fixture FS types happen to satisfy `first_inum ≤ root_inum` (verified live:
ext4 1≤2, FAT 2≤2, NTFS 0≤5), so the tests cannot catch a regression here.

**Fix:** Make the invariant explicit by always seeding the allocated-root into the
scan, decoupling the orphan check from the `first_inum` floor:

```python
def allocated_inodes(fs: pytsk3.FS_Info) -> frozenset[int]:
    allocated: set[int] = set()
    first = int(fs.info.first_inum)
    last = int(fs.info.last_inum)
    root = int(fs.info.root_inum)
    # Ensure the root inode is always probed even if it sits below first_inum,
    # so root-level deletions classify against a live parent (RECOV-02).
    for inum in {root, *range(first, last + 1)}:
        try:
            f = fs.open_meta(inode=inum)
        except OSError:
            continue
        m = f.info.meta
        if m is not None and int(m.flags) & _FS_META_FLAG_ALLOC:
            allocated.add(int(m.addr))
    return frozenset(allocated)
```

(Alternatively, special-case `resolved_parent_addr == int(fs.info.root_inum)` as
non-orphan in `iter_deleted_inodes` so the classification never depends on the
scan range at all.) Either way, add a fixture or unit test with
`first_inum > root_inum` so the invariant is pinned.

### WR-02: Hard-coded fixture inode addresses (`EXT4_DELETED_META_ADDR = 13`, `FAT_DELETED_META_ADDR = 4`) are an unverified, brittle ground-truth

**File:** `tests/fixtures/make_fixtures.py:113`, `:125` (and consumed by
`tests/test_filesystem.py:211`, `tests/test_recover.py:154,166`).

**Issue:** `EXT4_DELETED_META_ADDR = 13` is recorded as "debugfs assigns it
deterministically," and `FAT_DELETED_META_ADDR = 4` as "recorded post-build,"
but nothing in the build pipeline *asserts* the committed image actually carries
the deleted entry at that inode. The FAT builder's own docstring
(`make_fixtures.py:347-353`) admits the FAT image is **not byte-identical** across
rebuilds (mkfs.fat stamps a wall-clock volume id; mdel rewrites a dir entry in
place). If a future fixture rebuild shifts the deleted entry's inode (e.g. a
toolchain change in `debugfs`/`mkfs.fat` allocation order), the constant and the
committed image silently diverge: the `di.name == EXT4_DELETED_NAME` /
`di.meta_addr == FAT_DELETED_META_ADDR` filters would select the wrong row (or
nothing), and the regression's `assert ... is_orphan is False` could pass
vacuously or against a different entry — eroding the test's RECOV-02 guarantee.
Notably `EXT4_DELETED_META_ADDR` (13) collides with `EXT4_ORPHAN_META_ADDR` (13)
across two different images, making a copy/paste mix-up easy to miss.

**Fix:** Have the builders assert the recorded ground-truth at build time (the
fixtures are regenerated only on a host with the mkfs tools, so this is free in
CI). After `build_tiny_ext4_image` / `build_tiny_fat32_image`, reopen the image
via pytsk3 and assert the deleted entry's `meta.addr` equals the constant and is
UNALLOC — failing the regeneration loudly if allocation order drifts:

```python
def main() -> None:
    ...
    out = build_tiny_ext4_image(here / TINY_EXT4_NAME)
    _assert_deleted_inode(out, EXT4_DELETED_NAME, EXT4_DELETED_META_ADDR)
```

This converts a silent-divergence risk into a build-time failure.

## Info

### IN-01: `iter_deleted_inodes` opens each deleted root inode twice (`open_meta` in pass 1 *and* in `allocated_inodes`)

**File:** `src/pyautopsy/evidence/filesystem.py:462,478-484`

**Issue:** Pass 1 calls `allocated_inodes(fs)` (which opens every inode in range
via `open_meta`) and then, for each walked deleted entry, calls
`fs.open_meta(inode=addr)` *again* to read the ORPHAN flag. The seam already
collected enough per-inode state during the `allocated_inodes` scan to fold the
ORPHAN-flag read into it. This is duplicated native work, not a correctness bug
(performance is explicitly out of v1 scope), but it is the kind of redundant
seam round-trip worth noting for a later consolidation — a single
`scan_inodes(fs)` returning `{addr: (alloc, orphan)}` would serve
`allocated_inodes`, `allocated_data_blocks`, and the pass-1 ORPHAN read from one
pass.

**Fix:** (Optional, deferred.) Consolidate the per-inode scans behind one helper
that yields `(addr, flags)` and derive the allocated set / orphan flags from it.

### IN-02: Stale non-editable install can mask the fix outside the test harness

**File:** environment (`~/.local/lib/python3.14/site-packages/pyautopsy/...`) vs
`src/pyautopsy/` — surfaced while reviewing `src/pyautopsy/evidence/filesystem.py`.

**Issue:** A non-editable `pyautopsy` is installed in site-packages that predates
this fix. `import pyautopsy` from a plain REPL/script (no `PYTHONPATH=src`) loads
the *stale* module and exhibits the old buggy `is_orphan=True` for root-level
deletions. The test suite is correctly insulated (`pythonpath = ["src"]`), so
this does not affect CI or the review verdict — but it is a live "tested the
wrong copy" foot-gun for any developer validating the fix manually, and the
CLAUDE.md stack explicitly recommends an *editable* (`uv`/src-layout) install to
avoid exactly this.

**Fix:** Reinstall editable in the dev environment
(`uv pip install -e .` or `pip install -e .`) so `import pyautopsy` resolves to
`src/`, eliminating the divergence between ad-hoc runs and the pytest harness.

---

_Reviewed: 2026-05-31_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
