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

from pyautopsy.case import CaseStore
from pyautopsy.core.ingest import run_ingest
from pyautopsy.core.walk import WalkResult, run_walk
from tests.fixtures import make_fixtures

_NOT_YET = "Plan 02-02/02-03: core/walk.py orchestrator not implemented yet (RED)"

# Exact expected top-level entry count for the committed ext4 fixture: the
# known regular file, the deleted entry, lost+found, and $OrphanFiles — the
# 'every file' Nyquist signal (lost+found is empty, so there are no children).
_EXT4_EXPECTED_ROW_COUNT = 4


def _ingest_then_walk(
    image: Path, case_dir: Path, *, timezone: str = "UTC"
) -> tuple[WalkResult, int]:
    """Ingest ``image`` into ``case_dir`` then walk it; return (result, source_id)."""
    ingested = run_ingest(
        image, case_dir, examiner="X", evidence_id="E1"
    )
    result = run_walk(image, case_dir, timezone=timezone)
    return result, ingested.evidence_source_id


def test_inventory_includes_deleted_entry(
    tiny_ext4_image: Path, case_dir: Path
) -> None:
    """META-01/D-18: the inventory is complete and includes the DELETED entry.

    The walk records EXACTLY the fixture's entries (the 'every file' signal) and
    the known ``deleted.txt`` UNALLOC entry must be present with ``allocated=0``
    and a populated ``meta_addr``.
    """
    result, source_id = _ingest_then_walk(tiny_ext4_image, case_dir)

    with CaseStore.open(case_dir) as store:
        rows = store.get_files(source_id)

    assert len(rows) == _EXT4_EXPECTED_ROW_COUNT, [r.name for r in rows]
    assert result.files_inventoried == _EXT4_EXPECTED_ROW_COUNT
    assert result.volumes_walked == 1

    deleted = next(r for r in rows if r.name == make_fixtures.EXT4_DELETED_NAME)
    assert deleted.allocated is False
    assert deleted.meta_addr is not None
    assert result.deleted_count >= 1

    # The known regular file is present and allocated, tagged to volume 0 (bare).
    known = next(r for r in rows if r.name == make_fixtures.FS_FILE_NAME)
    assert known.allocated is True
    assert known.meta_addr is not None
    assert known.volume_id == 0
    assert known.fs_type == "ext"


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


def test_volume_tagging_on_partitioned_image(
    tiny_partitioned_image: Path, case_dir: Path
) -> None:
    """META-01/D-15: rows carry the correct volume_id/volume_offset per volume.

    The partitioned fixture (FAT + ext4) is walked as >=2 volumes; every file row
    must be tagged with a real (allocated) volume offset, and at least two
    distinct volume offsets must appear across the inventory.
    """
    result, source_id = _ingest_then_walk(tiny_partitioned_image, case_dir)

    with CaseStore.open(case_dir) as store:
        rows = store.get_files(source_id)

    assert result.volumes_walked >= 2
    assert rows, "partitioned image produced no file rows"
    offsets = {row.volume_offset for row in rows}
    assert len(offsets) >= 2, f"expected >=2 distinct volume offsets, got {offsets}"
    assert all(row.volume_offset > 0 for row in rows), offsets


def test_unsupported_volume_records_limitation(
    tiny_raw_image: Path, case_dir: Path
) -> None:
    """D-20: an unsupported volume -> limitation finding row; walk continues.

    A raw image with no recognisable filesystem makes ``FS_Info`` raise
    ``OSError`` on the bare-FS fallback volume. That is caught per-volume,
    recorded as an explicit known-limitation finding, and the walk completes
    (exit-clean) WITHOUT emitting any empty/garbage ``files`` rows for it.
    """
    result, source_id = _ingest_then_walk(tiny_raw_image, case_dir)

    assert result.limitations_recorded == 1
    assert result.volumes_walked == 0
    assert result.files_inventoried == 0

    with CaseStore.open(case_dir) as store:
        limitations = store.get_volume_limitations(source_id)
        files = store.get_files(source_id)

    assert len(limitations) == 1
    assert limitations[0].reason  # the FS_Info OSError message was recorded
    assert files == [], "no empty/garbage file rows for the unsupported volume"
