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
    open_fs,
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
