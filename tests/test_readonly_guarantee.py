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
