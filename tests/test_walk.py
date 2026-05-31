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


def _bytes_reader(data: bytes):
    """Return a read-only ``(offset, size) -> bytes`` closure over ``data``.

    Models the FS-seam ``read_random`` byte-reader so the hashing/typing helpers
    are exercised with no native object (D-06/D-14 testability contract).
    """

    def read_random(offset: int, size: int) -> bytes:
        return data[offset : offset + size]

    return read_random


def _reg_entry(reader, *, allocated: bool = True, size: int = 10):
    """Build a minimal regular-file ``FileEntry`` with the given content reader.

    Used by the WR-01/WR-02 unit tests to exercise ``_content_fields`` in
    isolation with a reader/typer that can raise, without needing a fixture image.
    """
    from pyautopsy.evidence.filesystem import FileEntry

    return FileEntry(
        name="x",
        path="/x",
        parent_addr=None,
        meta_addr=42,
        allocated=allocated,
        meta_type="reg",
        size=size,
        uid=0,
        gid=0,
        mode=0o644,
        mtime=0,
        atime=0,
        ctime=0,
        crtime=0,
        mtime_nano=0,
        atime_nano=0,
        ctime_nano=0,
        crtime_nano=0,
        fs_ftype=8192,
        volume_id=0,
        volume_offset=0,
        read_random=reader,
    )


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
    tiny_ext4_image: Path,
    tiny_fat32_image: Path,
    tiny_ntfs_image: Path,
    tmp_path: Path,
) -> None:
    """META-02: MACB stored tz-aware UTC ISO-8601 (+00:00); FAT flagged local.

    ext4/NTFS times are UTC; FAT times are local and must be flagged
    ``local-time-inferred`` with ``assumed_timezone`` (D-16). Zero -> None.
    ``timestamp_source`` carries the EXACT per-fs-type string (D-16).
    """
    # -- ext4: UTC times, exact timestamp_source ----------------------------
    ext4_case = tmp_path / "ext4_case"
    _, ext4_source = _ingest_then_walk(tiny_ext4_image, ext4_case)
    with CaseStore.open(ext4_case) as store:
        ext4_rows = store.get_files(ext4_source)
    ext4_file = next(r for r in ext4_rows if r.name == make_fixtures.FS_FILE_NAME)
    assert ext4_file.mtime_utc is not None and ext4_file.mtime_utc.endswith("+00:00")
    assert ext4_file.atime_utc is not None and ext4_file.atime_utc.endswith("+00:00")
    assert ext4_file.ctime_utc is not None and ext4_file.ctime_utc.endswith("+00:00")
    assert ext4_file.timestamp_source == "ext4:inode"
    # ext4/NTFS take the plain UTC path: no FAT local-time flag.
    assert (ext4_file.attributes or {}).get("time_precision") != "local-time-inferred"

    # -- NTFS: UTC times, exact timestamp_source ----------------------------
    ntfs_case = tmp_path / "ntfs_case"
    _, ntfs_source = _ingest_then_walk(tiny_ntfs_image, ntfs_case)
    with CaseStore.open(ntfs_case) as store:
        ntfs_rows = store.get_files(ntfs_source)
    ntfs_meta_rows = [r for r in ntfs_rows if r.mtime_utc is not None]
    assert ntfs_meta_rows, "NTFS walk produced no rows with MACB times"
    for r in ntfs_meta_rows:
        assert r.mtime_utc.endswith("+00:00")
        assert r.timestamp_source == "ntfs:$STANDARD_INFORMATION"

    # -- FAT: local-time-inferred flag + assumed_timezone + zero->None ------
    fat_case = tmp_path / "fat_case"
    _, fat_source = _ingest_then_walk(
        tiny_fat32_image, fat_case, timezone="America/New_York"
    )
    with CaseStore.open(fat_case) as store:
        fat_rows = store.get_files(fat_source)
    fat_file = next(r for r in fat_rows if r.name == make_fixtures.FS_FILE_NAME)
    assert fat_file.mtime_utc is not None and fat_file.mtime_utc.endswith("+00:00")
    assert fat_file.timestamp_source == "fat:dir-entry"
    assert fat_file.attributes is not None
    assert fat_file.attributes["time_precision"] == "local-time-inferred"
    assert fat_file.attributes["assumed_timezone"] == "America/New_York"
    # The FAT fixture's ctime epoch is 0 -> must read back as None, not 1970.
    assert fat_file.ctime_utc is None

    # CR-01 VALUE assertion: the FAT branch must ACTUALLY rebase the stored local
    # wall-clock to UTC, not merely re-label a no-op. The plain (non-FAT) UTC
    # interpretation of the SAME stored wall-clock components differs from the
    # correct FAT result by exactly the assumed-zone offset. Walking the same FAT
    # image as if its times were already UTC must therefore yield a DIFFERENT
    # mtime — if the two agree, the rebasing silently did nothing (the original
    # bug). New York is never UTC+0, so a real conversion is observable.
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    fat_utc_case = tmp_path / "fat_utc_case"
    _, fat_utc_source = _ingest_then_walk(
        tiny_fat32_image, fat_utc_case, timezone="UTC"
    )
    with CaseStore.open(fat_utc_case) as store:
        fat_utc_rows = store.get_files(fat_utc_source)
    fat_utc_file = next(
        r for r in fat_utc_rows if r.name == make_fixtures.FS_FILE_NAME
    )
    assert fat_utc_file.mtime_utc is not None
    ny_instant = datetime.fromisoformat(fat_file.mtime_utc)
    utc_instant = datetime.fromisoformat(fat_utc_file.mtime_utc)
    assert ny_instant != utc_instant, (
        "FAT local-time rebasing is a no-op: NY and UTC assumptions yielded the "
        "same instant (CR-01 regression)"
    )
    # The wall-clock the report claims (the UTC-assumed walk preserves it as-is),
    # when reinterpreted in NY and shifted to UTC, must equal the NY-assumed
    # instant — proving a true reinterpret rather than a re-render.
    naive_wall = utc_instant.replace(tzinfo=None)
    expected_ny = naive_wall.replace(tzinfo=ZoneInfo("America/New_York")).astimezone(
        timezone.utc
    )
    assert ny_instant == expected_ny


def test_macb_to_utc_iso_fat_reinterprets_local() -> None:
    """CR-01 unit: the FAT branch reinterprets the wall-clock in walk_tz.

    A direct test of ``_macb_to_utc_iso`` independent of any fixture: a stored FAT
    wall-clock of 12:00 under America/New_York must persist as 17:00:00+00:00
    (EST, UTC-5), NOT 12:00:00+00:00 (the no-op the original code produced).
    Non-FAT (``is_fat=False``) keeps the raw UTC epoch unchanged.
    """
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    from pyautopsy.core.walk import _macb_to_utc_iso

    # The stored wall-clock (2023-01-15 12:00:00, a winter date so NY is EST/UTC-5)
    # is encoded by TSK AS-IF it were a UTC epoch.
    wall = datetime(2023, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    secs = int(wall.timestamp())

    ny = ZoneInfo("America/New_York")
    fat_iso = _macb_to_utc_iso(secs, 0, is_fat=True, walk_tz=ny)
    assert fat_iso == "2023-01-15T17:00:00+00:00", fat_iso

    utc_iso = _macb_to_utc_iso(secs, 0, is_fat=False, walk_tz=ny)
    assert utc_iso == "2023-01-15T12:00:00+00:00", utc_iso

    # A zero epoch is "not recorded" -> None, never a fake 1970 (Pitfall 3).
    assert _macb_to_utc_iso(0, 0, is_fat=True, walk_tz=ny) is None


def test_fs_type_label_ext2_ext3_ext4() -> None:
    """CR-02 unit: ext2/ext3/ext4 enum values all label ``ext`` (not unknown).

    Feeds the real pytsk3 EXT2=128 / EXT3=256 / EXT4=8192 enum integers through
    the orchestrator's classifier and asserts the correct label + provenance, so
    an ext2/ext3 image can never silently fall through to ``unknown`` with a null
    ``timestamp_source`` again (the original bug used the FAT values {2,4,8}).
    """
    from pyautopsy.core.walk import _TIMESTAMP_SOURCE_BY_LABEL, _fs_type_label
    from pyautopsy.evidence.filesystem import (
        EXT_FS_TYPES,
        FAT_FS_TYPES,
        NTFS_FS_TYPES,
    )

    for ext_ftype in (128, 256, 8192):
        assert ext_ftype in EXT_FS_TYPES
        assert _fs_type_label(ext_ftype) == "ext"
        assert _TIMESTAMP_SOURCE_BY_LABEL.get(_fs_type_label(ext_ftype)) is not None

    # The {2,4,8} integers are FAT (NOT ext): they must label ``fat``, proving the
    # old _EXT_FTYPES={2,4,8} comment was wrong and is gone.
    for fat_ftype in (2, 4, 8):
        assert fat_ftype in FAT_FS_TYPES
        assert _fs_type_label(fat_ftype) == "fat"

    assert all(_fs_type_label(n) == "ntfs" for n in NTFS_FS_TYPES)
    assert _fs_type_label(999999) == "unknown"


def test_no_naive_datetimes(tiny_ext4_image: Path, case_dir: Path) -> None:
    """META-02 invariant: every *time column re-parses to an aware datetime.

    Routing every MACB value through ``iso_utc`` (which rejects naive) makes a
    naive timestamp structurally impossible; assert each non-null value ends in
    an explicit offset and re-parses aware.
    """
    from datetime import datetime

    _, source_id = _ingest_then_walk(tiny_ext4_image, case_dir)
    with CaseStore.open(case_dir) as store:
        rows = store.get_files(source_id)

    saw_a_time = False
    for row in rows:
        for value in (row.mtime_utc, row.atime_utc, row.ctime_utc, row.crtime_utc):
            if value is None:
                continue
            saw_a_time = True
            assert value.endswith("+00:00"), value
            parsed = datetime.fromisoformat(value)
            assert parsed.tzinfo is not None, value
            assert parsed.utcoffset() is not None, value
    assert saw_a_time, "no MACB times were persisted to assert against"


def test_ownership_and_mode(tiny_ext4_image: Path, case_dir: Path) -> None:
    """META-03: uid/gid/mode persisted and match the ext4 fixture ground truth.

    The committed ext4 file1.txt carries known uid/gid (recorded as the
    Plan 00 constants); the walk must persist uid/gid/mode exactly, and a
    meta-less entry's ownership must read back as ``None`` (never coerced to 0).
    """
    _, source_id = _ingest_then_walk(tiny_ext4_image, case_dir)
    with CaseStore.open(case_dir) as store:
        rows = store.get_files(source_id)

    known = next(r for r in rows if r.name == make_fixtures.FS_FILE_NAME)
    assert known.uid == make_fixtures.EXT4_FILE_UID
    assert known.gid == make_fixtures.EXT4_FILE_GID
    # The fixture set the permission bits via debugfs; they must persist as a
    # raw integer (not pre-formatted) and round-trip non-null for the real file.
    assert known.mode is not None
    assert isinstance(known.mode, int)

    # Every meta-bearing row carries integer ownership; only truly meta-less
    # rows keep None (never coerced to 0).
    for row in rows:
        if row.meta_addr is None:
            assert row.uid is None
            assert row.gid is None
            assert row.mode is None
        else:
            assert isinstance(row.uid, int)
            assert isinstance(row.gid, int)
            assert isinstance(row.mode, int)


def test_three_digest_single_pass(tiny_ext4_image: Path, tmp_path: Path) -> None:
    """META-04: MD5+SHA1+SHA256 per regular file in a single pass.

    Digests must match an independent ``hashlib`` pass; empty files get the
    sentinel digests; ``--max-hash-size`` skips oversized files and records a
    reason (D-17).
    """
    import hashlib

    from pyautopsy.evidence.integrity import EMPTY, hash_file

    # -- unit: hash_file matches a direct hashlib pass over the same bytes ----
    data = make_fixtures.FS_FILE_CONTENT * 137  # spans several 1 MiB-less reads
    reader = _bytes_reader(data)
    digests = hash_file(reader, len(data))
    assert digests is not None
    assert digests["md5"] == hashlib.md5(data).hexdigest()
    assert digests["sha1"] == hashlib.sha1(data).hexdigest()
    assert digests["sha256"] == hashlib.sha256(data).hexdigest()

    # -- unit: a zero-length file returns the well-known empty sentinels -----
    assert hash_file(_bytes_reader(b""), 0) == EMPTY
    assert EMPTY["md5"] == hashlib.md5(b"").hexdigest()
    assert EMPTY["sha1"] == hashlib.sha1(b"").hexdigest()
    assert EMPTY["sha256"] == hashlib.sha256(b"").hexdigest()

    # -- unit: a file over max_size is skipped (None — caller records reason) -
    assert hash_file(_bytes_reader(data), len(data), max_size=len(data) - 1) is None
    # -- unit: a short/truncated read records no partial digest (returns None) -
    assert hash_file(_bytes_reader(b"\x00" * 10), 1000) is None
    # -- unit: a non-positive chunk is rejected loudly (mirrors hash_image) ---
    with pytest.raises(ValueError):
        hash_file(_bytes_reader(data), len(data), chunk=0)

    # -- end-to-end: the walk hashes the known regular file with all three ---
    case_dir = tmp_path / "case"
    _, source_id = _ingest_then_walk(tiny_ext4_image, case_dir)
    with CaseStore.open(case_dir) as store:
        rows = store.get_files(source_id)

    known = next(r for r in rows if r.name == make_fixtures.FS_FILE_NAME)
    expected = make_fixtures.FS_FILE_CONTENT
    assert known.md5 == hashlib.md5(expected).hexdigest()
    assert known.sha1 == hashlib.sha1(expected).hexdigest()
    assert known.sha256 == hashlib.sha256(expected).hexdigest()

    # Non-regular entries (directories like lost+found, $OrphanFiles) are never
    # hashed: no content digest is recorded for them.
    for row in rows:
        if row.meta_type != "reg":
            assert row.md5 is None
            assert row.sha1 is None
            assert row.sha256 is None

    # -- end-to-end: --max-hash-size skips the file and records the reason ---
    skip_case = tmp_path / "skip_case"
    run_ingest(tiny_ext4_image, skip_case, examiner="X", evidence_id="E1")
    run_walk(tiny_ext4_image, skip_case, max_hash_size=1)
    with CaseStore.open(skip_case) as store:
        skip_rows = store.get_files(source_id)
    skipped = next(r for r in skip_rows if r.name == make_fixtures.FS_FILE_NAME)
    assert skipped.md5 is None
    assert skipped.sha1 is None
    assert skipped.sha256 is None
    assert (skipped.attributes or {}).get("hash_skipped") == "exceeds_max_hash_size"


def test_filetype_by_content_not_extension(
    tiny_ext4_image: Path, case_dir: Path
) -> None:
    """META-05: file_type derives from content, not extension.

    A text file is typed ``text/plain`` even with a misleading extension
    (content-signature via python-magic, D-19).
    """
    from pyautopsy.evidence import filetype

    # -- unit: content wins over a misleading extension. The signature engine
    # is fed bytes, never a name — a ``.png``-named text payload types text. ---
    misleading = filetype.file_type(_bytes_reader(b"just plain text\n"), 16)
    assert misleading == "text/plain"

    # -- end-to-end: the walk types the known regular file by content --------
    _, source_id = _ingest_then_walk(tiny_ext4_image, case_dir)
    with CaseStore.open(case_dir) as store:
        rows = store.get_files(source_id)

    known = next(r for r in rows if r.name == make_fixtures.FS_FILE_NAME)
    assert known.file_type == "text/plain"

    # Non-regular entries are never typed by a magic call on their dirent bytes.
    for row in rows:
        if row.meta_type != "reg":
            assert row.file_type in (None, "directory", "symlink")


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


def test_content_read_error_does_not_abort(monkeypatch) -> None:
    """WR-01: a per-entry content read failure degrades to null + continues.

    A reader/typer that raises ``OSError`` (the data-runs-gone case for a deleted
    entry) must NOT propagate out of ``_content_fields`` and abort the walk. The
    entry instead records null hashes, a null type, and a ``read_error`` reason —
    the spirit of D-20 / Pitfall 6 (one bad entry never destroys the run).
    """
    from pyautopsy.core import walk as walk_mod

    def boom(*_args, **_kwargs):
        raise OSError("data run gone")

    # hash_file raises on the content read.
    monkeypatch.setattr(walk_mod.integrity, "hash_file", boom)
    entry = _reg_entry(_bytes_reader(b"abc"), allocated=True)

    # The typer also raises; both must be swallowed.
    hashes, file_type, attributes = walk_mod._content_fields(
        entry, max_hash_size=None, typer=boom
    )

    assert hashes == {"md5": None, "sha1": None, "sha256": None}
    assert file_type is None
    assert attributes["hash_skipped"] == "read_error"


def test_unallocated_typing_flags_provenance() -> None:
    """WR-02: a deleted/unallocated regular file's type carries a reuse caveat.

    Typing an unallocated entry is still useful, but its blocks may have been
    reused (D-18: status only). The recorded type must therefore carry a
    ``file_type_provenance`` flag; an allocated file must NOT carry it.
    """
    from pyautopsy.core import walk as walk_mod

    def typer(_reader, _size):
        return "text/plain"

    # Unallocated: hashing is skipped (D-18) but typing runs and is flagged.
    unalloc = _reg_entry(_bytes_reader(b"deleted bytes"), allocated=False)
    hashes, file_type, attributes = walk_mod._content_fields(
        unalloc, max_hash_size=None, typer=typer
    )
    assert hashes == {"md5": None, "sha1": None, "sha256": None}
    assert file_type == "text/plain"
    assert (
        attributes["file_type_provenance"] == "unallocated-blocks-may-be-reused"
    )

    # Allocated: same type, but NO provenance caveat.
    alloc = _reg_entry(_bytes_reader(b"deleted bytes"), allocated=True)
    _, alloc_type, alloc_attrs = walk_mod._content_fields(
        alloc, max_hash_size=None, typer=typer
    )
    assert alloc_type == "text/plain"
    assert "file_type_provenance" not in alloc_attrs


def _read_audit(case_dir: Path) -> list[dict]:
    """Return the parsed audit-log events for a completed/aborted walk."""
    import json

    log = case_dir / "logs" / "audit.jsonl"
    return [
        json.loads(line)
        for line in log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_unexpected_error_audited_as_crashed_and_reraised(
    tiny_ext4_image: Path, case_dir: Path, monkeypatch
) -> None:
    """WR-05: a genuine bug is audited as ``walk.crashed`` (not ``walk.error``).

    An unexpected exception (here a ``KeyError`` injected into row-building) is a
    programming bug, not an operational failure. The walk must record it under a
    DISTINCT ``walk.crashed`` event so the audit trail never conflates it with an
    expected ``walk.error``, and must re-raise it unwrapped (traceback preserved).
    """
    from pyautopsy.core import walk as walk_mod

    run_ingest(tiny_ext4_image, case_dir, examiner="X", evidence_id="E1")

    def boom(*_args, **_kwargs):
        raise KeyError("simulated programming bug")

    monkeypatch.setattr(walk_mod, "_build_file_row", boom)

    with pytest.raises(KeyError):
        run_walk(tiny_ext4_image, case_dir)

    actions = [e["action"] for e in _read_audit(case_dir)]
    assert "walk.crashed" in actions
    assert "walk.error" not in actions


def test_expected_error_audited_as_error_and_reraised(
    tiny_ext4_image: Path, case_dir: Path
) -> None:
    """WR-05: an EXPECTED operational failure is audited as ``walk.error``.

    Pointing the walk at a case with no evidence source raises ``WalkError`` (an
    expected operational failure), which must be recorded as ``walk.error`` (not
    ``walk.crashed``) and re-raised.
    """
    from pyautopsy.case import CaseStore
    from pyautopsy.core.walk import WalkError

    # Build an empty case (no ingest) so _latest_evidence_source_id raises.
    CaseStore.create(case_dir).close()

    with pytest.raises(WalkError):
        run_walk(tiny_ext4_image, case_dir)

    actions = [e["action"] for e in _read_audit(case_dir)]
    assert "walk.error" in actions
    assert "walk.crashed" not in actions
