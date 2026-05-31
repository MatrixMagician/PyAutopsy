"""Shared pytest fixtures for the PyAutopsy suite.

Provides:

* ``case_dir`` — a fresh, empty case directory under ``tmp_path`` for each test.
* ``tiny_raw_image`` — the path to the committed, deterministic tiny raw image.
* ``tiny_ext4_image`` / ``tiny_ntfs_image`` / ``tiny_fat32_image`` /
  ``tiny_partitioned_image`` — committed tiny filesystem images for the Phase 2
  walk (built once with the host mkfs tools; CI needs no ``mkfs``).
* per-archive fixtures (``zip_slip_tar``, ``symlink_escape_tar``,
  ``device_file_tar``, ``ratio_bomb_zip``, ``count_bomb_tar``) that build each
  malicious archive into ``tmp_path`` on demand for the safe-extract plan
  (01-03) to consume. Building them lazily keeps live bombs off disk except for
  the test that needs them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures import make_fixtures

# Directory holding committed fixture assets (e.g. tiny_raw.dd).
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def case_dir(tmp_path: Path) -> Path:
    """Return a fresh, empty case directory under the test's tmp_path.

    The tool itself creates the ``logs/``/``exports/`` layout and ``case.db``;
    this fixture only provides the (non-existent) target path so each test gets
    an isolated case root.
    """
    return tmp_path / "case"


@pytest.fixture
def tiny_raw_image() -> Path:
    """Return the path to the committed deterministic tiny raw image.

    The image is a real >0-byte file under 1 MB that reads as raw bytes, used to
    prove read-only open and streaming-hash behaviour without a CI ``mkfs``
    dependency (01-RESEARCH.md A3).
    """
    image = FIXTURES_DIR / make_fixtures.TINY_RAW_NAME
    assert image.is_file(), f"committed fixture missing: {image}"
    return image


@pytest.fixture
def tiny_ext4_image() -> Path:
    """Path to the committed tiny ext4 image (one known file + a deleted entry).

    Built once with ``mkfs.ext4``/``debugfs`` and committed so CI needs no
    ``mkfs`` (02-RESEARCH); carries the known uid/gid/mode and the UNALLOC
    ``deleted.txt`` entry the META-01/03 walk tests assert against.
    """
    image = FIXTURES_DIR / make_fixtures.TINY_EXT4_NAME
    assert image.is_file(), f"committed fixture missing: {image}"
    return image


@pytest.fixture
def tiny_ntfs_image() -> Path:
    """Path to the committed tiny NTFS image (UTC times, system files present)."""
    image = FIXTURES_DIR / make_fixtures.TINY_NTFS_NAME
    assert image.is_file(), f"committed fixture missing: {image}"
    return image


@pytest.fixture
def tiny_fat32_image() -> Path:
    """Path to the committed tiny FAT32 image (FAT local-time test, D-16)."""
    image = FIXTURES_DIR / make_fixtures.TINY_FAT32_NAME
    assert image.is_file(), f"committed fixture missing: {image}"
    return image


@pytest.fixture
def tiny_partitioned_image() -> Path:
    """Path to the committed partitioned image (FAT + ext4 — volume-offset, D-15)."""
    image = FIXTURES_DIR / make_fixtures.TINY_PARTITIONED_NAME
    assert image.is_file(), f"committed fixture missing: {image}"
    return image


@pytest.fixture
def zip_slip_tar(tmp_path: Path) -> Path:
    """Build a Zip-Slip tar (``../../escape.txt``) into tmp_path."""
    return make_fixtures.build_zip_slip_tar(tmp_path / "zip_slip.tar")


@pytest.fixture
def symlink_escape_tar(tmp_path: Path) -> Path:
    """Build a symlink-escape tar (``link -> /etc/passwd``) into tmp_path."""
    return make_fixtures.build_symlink_escape_tar(tmp_path / "symlink_escape.tar")


@pytest.fixture
def device_file_tar(tmp_path: Path) -> Path:
    """Build a tar containing a character-device member into tmp_path."""
    return make_fixtures.build_device_file_tar(tmp_path / "device_file.tar")


@pytest.fixture
def ratio_bomb_zip(tmp_path: Path) -> Path:
    """Build a high-ratio/size-bomb zip into tmp_path."""
    return make_fixtures.build_ratio_bomb_zip(tmp_path / "ratio_bomb.zip")


@pytest.fixture
def count_bomb_tar(tmp_path: Path) -> Path:
    """Build a count-bomb tar (very many tiny members) into tmp_path."""
    return make_fixtures.build_count_bomb_tar(tmp_path / "count_bomb.tar")
