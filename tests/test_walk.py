"""Orchestrator tests for the filesystem walk (core/walk.py) — META-01..05 + D-20.

These are the RED Wave-0 scaffold covering the exact pytest node IDs from the
02-RESEARCH.md "Phase Requirements -> Test Map" / 02-VALIDATION.md Per-Task map.
They reference ``core.walk`` (the orchestrator Plan 02-02/02-03 builds) which
does not exist yet, so every test here MUST fail until those plans land.

Each stub is *collected and RED* (never skipped). The walk's "every file"
Nyquist signal is an EXACT row-count assertion per fixture (recorded ground
truth in ``tests/fixtures/make_fixtures.py``) — the implementation must make
these green, not merely spot-check.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_NOT_YET = "Plan 02-02/02-03: core/walk.py orchestrator not implemented yet (RED)"


def test_inventory_includes_deleted_entry(tiny_ext4_image: Path) -> None:
    """META-01: the inventory includes the known DELETED ext4 entry.

    The walk records every entry TSK yields incl. deleted ones, with
    allocated/unallocated status + inode/MFT address (D-18). The committed ext4
    fixture has a known ``deleted.txt`` UNALLOC entry that must appear.
    """
    pytest.fail(_NOT_YET)


def test_macb_utc_and_fat_flagged(
    tiny_ext4_image: Path, tiny_fat32_image: Path
) -> None:
    """META-02: MACB stored tz-aware UTC ISO-8601 (+00:00); FAT flagged local.

    ext4/NTFS times are UTC; FAT times are local and must be flagged
    ``local-time-inferred`` with ``assumed_timezone`` (D-16). Zero -> None.
    """
    pytest.fail(_NOT_YET)


def test_no_naive_datetimes(tiny_ext4_image: Path) -> None:
    """META-02 invariant: every *time column re-parses to an aware datetime.

    Routing every MACB value through ``iso_utc`` (which rejects naive) makes a
    naive timestamp structurally impossible; assert each non-null value ends in
    an explicit offset and re-parses aware.
    """
    pytest.fail(_NOT_YET)


def test_ownership_and_mode(tiny_ext4_image: Path) -> None:
    """META-03: uid/gid/mode persisted and match the ext4 fixture ground truth.

    The committed ext4 file1.txt carries known uid/gid/mode (recorded as
    constants); the walk must persist them exactly.
    """
    pytest.fail(_NOT_YET)


def test_three_digest_single_pass(tiny_ext4_image: Path) -> None:
    """META-04: MD5+SHA1+SHA256 per regular file in a single pass.

    Digests must match an independent ``hashlib`` pass; empty files get the
    sentinel digests; ``--max-hash-size`` skips oversized files and records a
    reason (D-17).
    """
    pytest.fail(_NOT_YET)


def test_filetype_by_content_not_extension(tiny_ext4_image: Path) -> None:
    """META-05: file_type derives from content, not extension.

    A text file is typed ``text/plain`` even with a misleading extension
    (content-signature via python-magic, D-19).
    """
    pytest.fail(_NOT_YET)


def test_unsupported_volume_records_limitation(tiny_partitioned_image: Path) -> None:
    """D-20: an unsupported/garbage-offset volume -> limitation finding row.

    ``FS_Info`` raising ``OSError`` is caught per-volume, recorded as an explicit
    known-limitation finding, and the walk continues to other volumes — never an
    empty/garbage row and never an aborted run.
    """
    pytest.fail(_NOT_YET)
