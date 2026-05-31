"""Tests for the read-only evidence guarantee (INGEST-03).

Proves the source image is provably never modified across open + hash (mtime and
size unchanged) and that ``assert_source_not_mounted`` refuses a source path that
appears in a (synthetic, injected) ``/proc/mounts`` table — the mounted-source
guard from PITFALLS P1 / ASVS V4, exercised without touching the host's real
mount table.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyautopsy.evidence.image import open_image
from pyautopsy.evidence.integrity import (
    MountedSourceError,
    assert_source_not_mounted,
    hash_image,
)


def test_source_mtime_and_size_unchanged_after_open_and_hash(
    tiny_raw_image: Path,
) -> None:
    """Open + hash leaves the source file's mtime and size untouched."""
    before = tiny_raw_image.stat()
    with open_image(tiny_raw_image) as handle:
        hash_image(handle)
        hash_image(handle)  # re-verify pass too
    after = tiny_raw_image.stat()
    assert after.st_mtime_ns == before.st_mtime_ns
    assert after.st_size == before.st_size


def test_source_unchanged_after_walk(
    tiny_ext4_image: Path, tmp_path: Path
) -> None:
    """D-05/P1: a full filesystem walk never modifies the source.

    Mirrors ``test_source_mtime_and_size_unchanged_after_open_and_hash`` for the
    walk path: stat before, ingest + run the full walk over the fs fixture, stat
    after, assert ``st_mtime_ns`` + ``st_size`` unchanged (the walk reads only
    through the TSK File object and never mounts/writes the source).
    """
    from pyautopsy.core.ingest import run_ingest
    from pyautopsy.core.walk import run_walk

    case_dir = tmp_path / "case"
    before = tiny_ext4_image.stat()
    run_ingest(tiny_ext4_image, case_dir, examiner="X", evidence_id="E1")
    run_walk(tiny_ext4_image, case_dir)
    after = tiny_ext4_image.stat()

    assert after.st_mtime_ns == before.st_mtime_ns
    assert after.st_size == before.st_size


def test_recover_does_not_write_source(
    ntfs_resident_deleted_image: Path, tmp_path: Path
) -> None:
    """D-42: deleted-file recovery never modifies the source image.

    Mirrors ``test_source_unchanged_after_walk`` for the recovery path: stat the
    source before, run ``ingest`` + ``walk`` + ``recover`` (which reopens each
    deleted inode read-only and writes ONLY under ``<case>/recovered/``), stat
    after, and assert ``st_mtime_ns`` + ``st_size`` are unchanged — the source
    bytes are provably untouched. The Phase-1 end-of-run re-verify still ran
    (it lives inside ``run_ingest``), and a second ``assert_source_not_mounted``
    confirms the read-only-boundary guard is re-asserted (the same guard
    ``run_recover`` re-asserts before any access).
    """
    from pyautopsy.core.ingest import run_ingest
    from pyautopsy.core.recover import run_recover
    from pyautopsy.core.walk import run_walk

    case_dir = tmp_path / "case"
    before = ntfs_resident_deleted_image.stat()

    run_ingest(
        ntfs_resident_deleted_image, case_dir, examiner="X", evidence_id="E1"
    )
    run_walk(ntfs_resident_deleted_image, case_dir)
    result = run_recover(ntfs_resident_deleted_image, case_dir)

    after = ntfs_resident_deleted_image.stat()

    # The source image is provably never written: identical mtime + size (D-42).
    assert after.st_mtime_ns == before.st_mtime_ns
    assert after.st_size == before.st_size

    # Sanity: recovery actually did work (so this is not a vacuous read-only
    # pass over a no-op), and recovered bytes landed ONLY under the case dir.
    assert result.files_recovered >= 1
    recovered_root = case_dir / "recovered"
    assert recovered_root.is_dir()
    for recovered in recovered_root.rglob("*"):
        if recovered.is_file():
            # Every recovered byte is confined to the case dir, never the source.
            assert recovered_root in recovered.resolve().parents

    # The read-only-boundary guard is re-assertable on the source after recovery
    # (it is not a mountpoint), the same guard run_recover re-asserts (D-42/P1).
    assert_source_not_mounted(ntfs_resident_deleted_image)


def _mounts_table(*device_mount_pairs: tuple[str, str]) -> str:
    """Build a synthetic /proc/mounts body from (device, mountpoint) pairs."""
    return "".join(
        f"{dev} {mnt} ext4 ro,relatime 0 0\n" for dev, mnt in device_mount_pairs
    )


def test_assert_not_mounted_allows_unmounted_path(tmp_path: Path) -> None:
    """A path absent from the mounts table is permitted."""
    image = tmp_path / "evidence.dd"
    image.write_bytes(b"\x00" * 16)
    mounts = _mounts_table(("/dev/sda1", "/"), ("/dev/sdb1", "/boot"))
    # Must not raise.
    assert_source_not_mounted(image, mounts_text=mounts)


def test_assert_not_mounted_refuses_mounted_path(tmp_path: Path) -> None:
    """A path that IS a mountpoint is refused (P1)."""
    mountpoint = tmp_path / "mounted_evidence"
    mountpoint.mkdir()
    mounts = _mounts_table(
        ("/dev/sda1", "/"),
        ("/dev/loop0", str(mountpoint)),
    )
    with pytest.raises(MountedSourceError):
        assert_source_not_mounted(mountpoint, mounts_text=mounts)


def test_assert_not_mounted_allows_file_residing_on_a_mount(tmp_path: Path) -> None:
    """An ordinary image file that merely *resides on* a mount is allowed.

    Only a path that is itself a mountpoint root is the actionable "mounted
    evidence filesystem" signal (P1); a raw image stored under a non-root
    partition is a normal, permitted case and must not be refused — otherwise
    the guard would reject evidence on any host where ``/home`` / ``/tmp`` is a
    separate mount.
    """
    mountpoint = tmp_path / "mnt"
    mountpoint.mkdir()
    image = mountpoint / "subdir" / "evidence.dd"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"\x00" * 16)
    mounts = _mounts_table(("/dev/loop0", str(mountpoint)))
    # The file is under the mount but is not the mountpoint itself -> allowed.
    assert_source_not_mounted(image, mounts_text=mounts)


def test_assert_not_mounted_default_reads_proc_mounts(tmp_path: Path) -> None:
    """Without an injected table the guard consults the real /proc/mounts.

    A fresh temp file is not a mountpoint, so this must pass on any normal host
    (including hosts where the temp dir lives on a separate tmpfs mount).
    """
    image = tmp_path / "evidence.dd"
    image.write_bytes(b"\x00" * 16)
    assert_source_not_mounted(image)  # must not raise
