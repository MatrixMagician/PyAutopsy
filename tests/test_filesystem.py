"""Seam-level tests for the FS-layer native seam (evidence/filesystem.py).

These cover the D-14 FS seam Plan 02-01 builds: volume enumeration (mmls
equivalent), bare-filesystem fallback to offset 0, FS-type detection, and
recursion correctness over the committed fixture images (02-VALIDATION.md
Per-Task map).

The seam yields plain :class:`FileEntry` value objects (frozen dataclasses of
primitives + one byte-reader callable); no pytsk3 type may leak past it.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pyautopsy.evidence.filesystem import (
    FAT_FS_TYPES,
    FileEntry,
    enumerate_volumes,
    iter_deleted_inodes,
    open_fs,
    recover_meta,
    walk_fs,
)
from pyautopsy.evidence.image import open_image
from tests.fixtures import make_fixtures

# Ground truth for the committed ext4 fixture (recorded in make_fixtures.py +
# verified empirically against the image): the root holds lost+found (dir),
# the known regular file, the deleted entry, and the $OrphanFiles virtual dir.
_EXT4_EXPECTED_NAMES = {
    "lost+found",
    make_fixtures.FS_FILE_NAME,
    make_fixtures.EXT4_DELETED_NAME,
    "$OrphanFiles",
}


def _walk_all(image: Path) -> list[FileEntry]:
    """Walk every allocated volume of ``image`` and collect all FileEntry rows."""
    rows: list[FileEntry] = []
    with open_image(image) as handle:
        for vol in enumerate_volumes(handle.image):
            try:
                fs = open_fs(handle.image, vol.offset)
            except OSError:
                continue
            rows.extend(walk_fs(fs, vol.volume_id, vol.offset))
    return rows


def test_volume_enumeration(tiny_partitioned_image: Path) -> None:
    """META-01/D-15: enumerate every volume with id + distinct byte offset.

    The partitioned fixture (FAT + ext4) must yield two *allocated* volumes whose
    byte offsets are ``part.start * block_size`` and are distinct (Open Question
    A1); the volume-system metadata partition and unallocated gaps are skipped.
    """
    with open_image(tiny_partitioned_image) as handle:
        volumes = list(enumerate_volumes(handle.image))

    assert len(volumes) >= 2, volumes
    offsets = [v.offset for v in volumes]
    assert len(set(offsets)) == len(offsets), f"offsets not distinct: {offsets}"
    # Every enumerated volume must actually open as a filesystem (no garbage).
    with open_image(tiny_partitioned_image) as handle:
        for vol in volumes:
            fs = open_fs(handle.image, vol.offset)
            assert int(fs.info.ftype) > 0


def test_bare_fs_fallback(tiny_ext4_image: Path) -> None:
    """META-01/D-15: a bare-FS image (no partition table) opens at offset 0.

    ``Volume_Info`` raises ``OSError`` on a bare filesystem; the seam falls back
    to exactly one volume ``(volume_id=0, offset=0)`` rather than failing.
    """
    with open_image(tiny_ext4_image) as handle:
        volumes = list(enumerate_volumes(handle.image))

    assert len(volumes) == 1
    assert volumes[0].volume_id == 0
    assert volumes[0].offset == 0


def test_fs_type_detection(
    tiny_ext4_image: Path, tiny_ntfs_image: Path, tiny_fat32_image: Path
) -> None:
    """META-01/META-02: the seam reports the correct fs type per fixture.

    FAT must be recognisable via the pytsk3-free ``FAT_FS_TYPES`` contract (it
    drives the D-16 local-time handling downstream); ext4/NTFS must NOT be in
    that set.
    """
    with open_image(tiny_fat32_image) as handle:
        fat_fs = open_fs(handle.image, 0)
        assert int(fat_fs.info.ftype) in FAT_FS_TYPES

    for image in (tiny_ext4_image, tiny_ntfs_image):
        with open_image(image) as handle:
            fs = open_fs(handle.image, 0)
            assert int(fs.info.ftype) > 0
            assert int(fs.info.ftype) not in FAT_FS_TYPES


def test_recursion_correctness(tiny_ext4_image: Path) -> None:
    """META-01: recursion visits every entry once, skips '.'/'..', guards loops.

    The yielded set of names must include the ext4 fixture ground truth (the
    'every file' signal) and contain no duplicate (path, meta_addr) pairs — the
    inode seen-set must prevent re-counting.
    """
    rows = _walk_all(tiny_ext4_image)
    names = {row.name for row in rows}
    assert _EXT4_EXPECTED_NAMES <= names, (names, _EXT4_EXPECTED_NAMES)
    assert "." not in names and ".." not in names

    # No (path, meta_addr) visited twice — the loop guard holds.
    seen_keys = [(row.path, row.meta_addr) for row in rows]
    assert len(seen_keys) == len(set(seen_keys)), "an entry was yielded twice"


def test_deleted_entry_is_unallocated_with_meta_addr(tiny_ext4_image: Path) -> None:
    """META-01/D-18: the deleted ext4 entry is unallocated but keeps its addr."""
    rows = _walk_all(tiny_ext4_image)
    deleted = next(r for r in rows if r.name == make_fixtures.EXT4_DELETED_NAME)
    assert deleted.allocated is False
    assert deleted.meta_addr is not None


def test_no_native_types_leak_past_the_seam(tiny_ext4_image: Path) -> None:
    """D-14: FileEntry is a frozen dataclass of plain types + one callable.

    Asserts every yielded FileEntry carries only primitives (or None) and that
    ``read_random`` is a plain Callable, never a native pytsk3 ``File`` object.
    """
    rows = _walk_all(tiny_ext4_image)
    plain = (str, int, bool, type(None))
    for row in rows:
        for value in (
            row.name,
            row.path,
            row.meta_addr,
            row.allocated,
            row.meta_type,
            row.size,
            row.fs_ftype,
            row.volume_id,
            row.volume_offset,
        ):
            assert isinstance(value, plain), (row.name, value)
        if row.read_random is not None:
            assert isinstance(row.read_random, Callable)
            assert type(row.read_random).__module__ != "pytsk3"


def test_fat_fs_types_is_plain_int_frozenset() -> None:
    """D-14: FAT_FS_TYPES is an importable frozenset[int] (pytsk3-free contract)."""
    assert isinstance(FAT_FS_TYPES, frozenset)
    assert FAT_FS_TYPES
    assert all(isinstance(t, int) and type(t) is int for t in FAT_FS_TYPES)


def test_root_entries_carry_root_inode_parent_addr(tiny_ext4_image: Path) -> None:
    """WR-03/RECOV-02: root-level entries carry ``parent_addr == fs root inode``.

    Corrected contract (was ``parent_addr is None``): ``walk_fs`` now tags every
    top-level entry with the filesystem root inode (``fs.info.root_inum``) so a
    deleted file in the root carries an *allocated* parent and classifies as
    recovered, NOT as an orphan. ``None`` is reserved exclusively for the pass-2
    range-scan orphan (no surviving directory link). This pins the column so it
    can never silently revert to a hardcoded ``None`` everywhere (which was the
    original RECOV-02 root-level-deletion bug). A revert FAILS here.
    """
    with open_image(tiny_ext4_image) as handle:
        fs = open_fs(handle.image, 0)
        root_inum = int(fs.info.root_inum)
        rows = list(walk_fs(fs, 0, 0))
    assert rows
    for row in rows:
        # The ext4 fixture is flat: lost+found and $OrphanFiles are empty, so
        # every yielded entry is at the root and must carry the root inode (NOT
        # None — None is now reserved for genuine range-scan orphans).
        assert row.parent_addr == root_inum, (row.name, row.parent_addr, root_inum)


def test_root_level_deletion_is_not_orphan(
    tiny_ext4_image: Path, tiny_fat32_image: Path
) -> None:
    """RECOV-02: a deleted file in the volume ROOT classifies is_orphan=False.

    Regression for the root-level misclassification gap, pinned for BOTH ext4
    and FAT: ``walk_fs`` now tags root entries with the filesystem root inode, so
    ``iter_deleted_inodes`` sees an allocated parent for a root-level deletion
    (ext4 ``deleted.txt`` / the FAT root deletion) and does NOT flag it as an
    orphan. ``None`` is reserved for genuine range-scan orphans with no surviving
    dir link. A revert (root entries back to ``parent_addr=None``) would re-flag
    these as orphans and FAIL this test.
    """
    # ext4 root deletion (matched by name + recorded inode).
    with open_image(tiny_ext4_image) as handle:
        fs = open_fs(handle.image, 0)
        ext4_deleted = [
            di
            for di in iter_deleted_inodes(fs, volume_id=0, volume_offset=0)
            if di.name == make_fixtures.EXT4_DELETED_NAME
        ]
    assert ext4_deleted, "root-level deleted.txt was not discovered (ext4)"
    di = ext4_deleted[0]
    assert di.meta_addr == make_fixtures.EXT4_DELETED_META_ADDR
    assert di.is_orphan is False, "ext4 root deletion wrongly classified orphan"
    assert di.parent_addr is not None, "ext4 root deletion must carry the root inode"

    # FAT root deletion (FAT loses the first name char, so match by recorded
    # inode, not exact name).
    with open_image(tiny_fat32_image) as handle:
        fs = open_fs(handle.image, 0)
        fat_deleted = [
            di
            for di in iter_deleted_inodes(fs, volume_id=0, volume_offset=0)
            if di.meta_addr == make_fixtures.FAT_DELETED_META_ADDR
        ]
    assert fat_deleted, "root-level FAT deletion was not discovered"
    fdi = fat_deleted[0]
    assert fdi.is_orphan is False, "FAT root deletion wrongly classified orphan"
    assert fdi.parent_addr is not None, "FAT root deletion must carry the root inode"


def test_removed_parent_deletion_is_still_orphan(ext4_orphan_image: Path) -> None:
    """RECOV-02: a deletion whose parent DIR was removed still classifies orphan.

    Pins the OTHER direction so the root-inode fix cannot swallow a genuine
    orphan (threat T-04-04-UNDERCLAIM): the ext4_orphan fixture's file
    (``EXT4_ORPHAN_META_ADDR``) had BOTH itself and its parent directory removed,
    so its surviving ``parent_addr`` is an *unallocated* inode — it must still
    classify ``is_orphan=True``.
    """
    with open_image(ext4_orphan_image) as handle:
        fs = open_fs(handle.image, 0)
        orphans = [
            di
            for di in iter_deleted_inodes(fs, volume_id=0, volume_offset=0)
            if di.meta_addr == make_fixtures.EXT4_ORPHAN_META_ADDR
        ]
    assert orphans, "orphan inode was not discovered"
    assert orphans[0].is_orphan is True, (
        "removed-parent deletion wrongly demoted to non-orphan (genuine orphan "
        "must be preserved)"
    )


def test_parent_addr_threaded_through_recursion() -> None:
    """WR-03/RECOV-02: a child's ``parent_addr`` is its parent directory's inode.

    Uses a fake pytsk3-shaped filesystem (root contains one subdirectory which
    contains one regular file) so the recursion is exercised without a fixture.
    Corrected contract: a root-level entry now carries the FakeFS root inode
    (``fs.info.root_inum``), NOT ``None`` — ``None`` is reserved for genuine
    range-scan orphans, and a root-level deletion must classify as recovered. The
    child under ``sub/`` still carries ``parent_addr == sub.inode`` (the threading
    below the root is unchanged).
    """
    from tests.fixtures.fake_fs import FakeDirEntry, FakeFS

    fs = FakeFS(
        {
            "/": [FakeDirEntry("sub", addr=10, is_dir=True)],
            "/sub": [FakeDirEntry("file.txt", addr=11, is_dir=False)],
        },
        root_inum=2,
    )
    rows = list(walk_fs(fs, volume_id=0, volume_offset=0))
    sub = next(r for r in rows if r.name == "sub")
    child = next(r for r in rows if r.name == "file.txt")
    assert sub.parent_addr == 2  # sub is at the root → tagged with the root inode
    assert child.parent_addr == sub.meta_addr == 10


def test_recover_meta_reader_survives_subsequent_inode_iteration(
    ext4_orphan_image: Path,
) -> None:
    """WR-05: a recover_meta read_random closure stays valid after later opens.

    recover_meta returns a ``read_random`` closure that captures the TSK ``File``
    ``f`` from ``open_meta``; the File's lifetime is bound only by that closure
    capture. The recovery orchestrator calls the reader ACROSS the recover_meta
    return boundary and AFTER ``iter_deleted_inodes`` has opened other ``open_meta``
    handles on the same ``fs``. This pins that contract: capture the orphan inode's
    reader FIRST, then iterate every deleted inode on the same fs (each opening
    fresh native File handles), and only THEN read — the bytes must still be exact.
    A future refactor that drops the closure capture (e.g. extracts bytes eagerly)
    would GC the File and make this read return garbage / fail, catching the
    regression.
    """
    with open_image(ext4_orphan_image) as handle:
        fs = open_fs(handle.image, 0)

        # 1. Capture the orphan inode's reader BEFORE touching any other inode.
        entry = recover_meta(fs, make_fixtures.EXT4_ORPHAN_META_ADDR)
        assert entry is not None, "orphan inode did not reopen via recover_meta"
        assert entry.read_random is not None, "orphan inode carried no reader"
        captured_reader = entry.read_random
        size = entry.size

        # 2. Iterate every deleted inode on the SAME fs — this opens many further
        #    native open_meta handles, exactly as the orchestrator does between
        #    recover_meta and the deferred read. Force full materialization.
        discovered = list(iter_deleted_inodes(fs, volume_id=0, volume_offset=0))
        assert discovered, "no deleted inodes discovered on the orphan fixture"

        # 3. NOW read through the originally-captured closure. If the File were
        #    not pinned alive by the closure, this would be use-after-free.
        recovered_bytes = captured_reader(0, size)

    assert recovered_bytes == make_fixtures.EXT4_ORPHAN_CONTENT, (
        "recover_meta reader returned wrong bytes after iterating other inodes "
        "(File lifetime not held across the return boundary)"
    )


def test_recursion_depth_is_capped() -> None:
    """WR-04: adversarial deep nesting stops at the cap, never RecursionError.

    A fake filesystem of self-referential-by-name directories (each level a new
    inode so the inode seen-set never fires) would recurse unbounded; the depth
    cap must stop descent at :data:`_MAX_WALK_DEPTH` and return cleanly rather
    than blowing the Python stack and aborting the walk.
    """
    from pyautopsy.evidence.filesystem import _MAX_WALK_DEPTH
    from tests.fixtures.fake_fs import DeepFakeFS

    fs = DeepFakeFS()  # every directory contains one deeper directory, forever
    rows = list(walk_fs(fs, volume_id=0, volume_offset=0))

    # Descent stopped at the cap without raising RecursionError. An entry is
    # yielded at each recursion level BEFORE the cap is checked, so levels
    # 0.._MAX_WALK_DEPTH inclusive each emit one row (the level at the cap emits
    # its own entry, then refuses to descend further).
    assert len(rows) == _MAX_WALK_DEPTH + 1
