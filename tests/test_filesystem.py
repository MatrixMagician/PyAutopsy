"""Seam-level tests for the FS-layer native seam (evidence/filesystem.py).

These are the RED Wave-0 scaffold for the D-14 FS seam that Plan 02-01 builds:
volume enumeration (mmls equivalent), bare-filesystem fallback to offset 0,
FS-type detection, and recursion correctness over the committed fixture images
(02-VALIDATION.md Per-Task map). They reference ``evidence.filesystem``, which
does not exist yet, so every test here MUST fail until Plan 02-01 lands the seam.

Each stub is *collected and RED* (never skipped) — the Nyquist scaffold needs a
red target to turn green, not an absent one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_NOT_YET = "Plan 02-01: evidence/filesystem.py FS seam not implemented yet (RED)"


def test_volume_enumeration(tiny_partitioned_image: Path) -> None:
    """META-01: enumerate every volume on a partitioned image with id + offset.

    The walk must open both the FAT and the ext4 partition at
    ``part.start * block_size`` and tag rows with the right volume_id/offset
    (D-15, Open Question A1).
    """
    pytest.fail(_NOT_YET)


def test_bare_fs_fallback(tiny_ext4_image: Path) -> None:
    """META-01/D-15: a bare-FS image (no partition table) opens at offset 0.

    ``Volume_Info`` raises ``OSError`` on a bare filesystem; the seam falls back
    to a single volume at offset 0 rather than failing.
    """
    pytest.fail(_NOT_YET)


def test_fs_type_detection(
    tiny_ext4_image: Path, tiny_ntfs_image: Path, tiny_fat32_image: Path
) -> None:
    """META-01/META-02: the seam reports the correct fs type per fixture.

    ext4/NTFS/FAT32 must each be detected (FAT typing drives the D-16 local-time
    handling downstream).
    """
    pytest.fail(_NOT_YET)


def test_recursion_correctness(tiny_ext4_image: Path) -> None:
    """META-01: recursion visits every entry once, skips '.'/'..', guards loops.

    Inode seen-set + ``.``/``..`` skip (RESEARCH Pattern 2); the yielded count
    must equal the fixture ground truth (the 'every file' signal).
    """
    pytest.fail(_NOT_YET)
