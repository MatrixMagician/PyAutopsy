"""Shared pytest fixtures for the PyAutopsy suite.

Provides:

* ``case_dir`` — a fresh, empty case directory under ``tmp_path`` for each test.
* ``tiny_raw_image`` — the path to the committed, deterministic tiny raw image.
* ``tiny_ext4_image`` / ``tiny_ntfs_image`` — committed tiny filesystem images
  for the Phase 2 walk (built once with the host mkfs tools; CI needs no
  ``mkfs``).
* ``tiny_fat32_image`` / ``tiny_partitioned_image`` — **generated at test time**
  (session-scoped) rather than committed, because the FAT volume is large
  (64–74 MiB) and not byte-deterministic (``mkfs.fat`` stamps a wall-clock
  volume id). Built once per session from the host mkfs/mtools tools; a host
  lacking those tools ``skip``s the dependent tests rather than failing.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from tests.fixtures import make_fixtures

# Directory holding committed fixture assets (e.g. tiny_raw.dd).
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _build_or_skip(builder: Any, dest: Path, *tools: str) -> Path:
    """Build a generated-at-test-time fixture, or ``skip`` if a tool is missing.

    The large, non-byte-deterministic FAT images (``tiny_fat32`` /
    ``tiny_partitioned``) are not committed; they are built on demand from the
    host mkfs/mtools tools. When those tools are absent (e.g. a minimal CI
    image), the dependent tests are skipped with an actionable message rather
    than hard-failing.
    """
    missing = [t for t in tools if shutil.which(t) is None]
    if missing:
        pytest.skip(
            "generated-at-test-time fixture needs "
            f"{', '.join(missing)} on PATH (Fedora: dosfstools/mtools/e2fsprogs/"
            "util-linux). Image is not committed; install the tools to run this test."
        )
    return builder(dest)


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


@pytest.fixture(scope="session")
def tiny_fat32_image(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generated-at-test-time tiny FAT32 image (FAT local-time test, D-16).

    Built once per session into a session tmp dir (not committed) because the
    FAT volume is 64 MiB and ``mkfs.fat`` is not byte-deterministic. Skips if the
    mkfs/mtools tools are absent.
    """
    dest = tmp_path_factory.mktemp("fs_fixtures") / make_fixtures.TINY_FAT32_NAME
    return _build_or_skip(
        make_fixtures.build_tiny_fat32_image, dest, "mkfs.fat", "mcopy", "mdel"
    )


@pytest.fixture(scope="session")
def tiny_partitioned_image(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generated-at-test-time partitioned image (FAT + ext4 — volume-offset, D-15).

    Built once per session into a session tmp dir (not committed) because the
    image is 74 MiB and its FAT partition is not byte-deterministic. Skips if the
    sfdisk/mkfs/mtools tools are absent.
    """
    dest = tmp_path_factory.mktemp("fs_fixtures") / make_fixtures.TINY_PARTITIONED_NAME
    return _build_or_skip(
        make_fixtures.build_partitioned_image,
        dest,
        "sfdisk",
        "mkfs.fat",
        "mkfs.ext4",
        "mcopy",
    )


@pytest.fixture
def ext4_orphan_image() -> Path:
    """Path to the committed ext4 image with an ORPHAN file (RECOV-02).

    A regular file whose parent directory was deleted, so its inode (recorded as
    ``make_fixtures.EXT4_ORPHAN_META_ADDR``) survives with no path back to root.
    """
    image = FIXTURES_DIR / make_fixtures.EXT4_ORPHAN_NAME
    assert image.is_file(), f"committed fixture missing: {image}"
    return image


@pytest.fixture
def ext4_overwritten_image() -> Path:
    """Path to the committed ext4 image with an OVERWRITTEN deleted entry (RECOV-03)."""
    image = FIXTURES_DIR / make_fixtures.EXT4_OVERWRITTEN_NAME
    assert image.is_file(), f"committed fixture missing: {image}"
    return image


@pytest.fixture
def ntfs_resident_deleted_image() -> Path:
    """Path to the committed NTFS image with a RESIDENT deleted file (RECOV-01)."""
    image = FIXTURES_DIR / make_fixtures.NTFS_RESIDENT_NAME
    assert image.is_file(), f"committed fixture missing: {image}"
    return image


@pytest.fixture
def nsrl_minimal_db() -> Path:
    """Path to the committed NSRL ``FILE``-table fixture DB (FILTER-01, Pitfall 4)."""
    db = FIXTURES_DIR / make_fixtures.NSRL_MINIMAL_NAME
    assert db.is_file(), f"committed fixture missing: {db}"
    return db


@pytest.fixture
def nsrl_metadata_db() -> Path:
    """Path to the committed NSRL ``METADATA``-table variant fixture DB (FILTER-01)."""
    db = FIXTURES_DIR / make_fixtures.NSRL_METADATA_NAME
    assert db.is_file(), f"committed fixture missing: {db}"
    return db


@pytest.fixture
def log_search_image() -> Path:
    """Path to the committed Phase-5 log/search ext4 image (LOG-/SEARCH- corpus).

    Built once with ``mkfs.ext4``/``debugfs`` and committed so CI needs no
    ``mkfs`` (mirrors the Phase-2/4 fixtures). Carries the rotated/gz ``auth.log``
    set, ``syslog``, per-user ``.bash_history``/``.zsh_history``, the
    ``/etc/localtime`` symlink + ``/etc/timezone`` text, planted allocated +
    unallocated search needles, an IOC term, a known-bad-hash file, and the two
    CR-01 tied-second syslog lines. Ground truth is in :func:`log_search_groundtruth`.
    """
    image = FIXTURES_DIR / make_fixtures.LOG_SEARCH_NAME
    assert image.is_file(), f"committed fixture missing: {image}"
    return image


@pytest.fixture
def log_search_groundtruth() -> dict[str, Any]:
    """Return the committed ground-truth constants for :func:`log_search_image`.

    Loads ``log_search_groundtruth.json`` (committed next to the image) so a test
    can assert exact values — the inferred timezone + year, planted allocated and
    unallocated needles and their offsets, the IOC term, the known-bad hash hex,
    and the tied-event count — without importing the mkfs-dependent builder.
    """
    sidecar = FIXTURES_DIR / make_fixtures.LOG_SEARCH_GROUNDTRUTH_NAME
    assert sidecar.is_file(), f"committed ground-truth sidecar missing: {sidecar}"
    return json.loads(sidecar.read_text(encoding="utf-8"))
