"""Deterministic builders for test evidence and malicious-archive fixtures.

Three kinds of fixture are produced here:

* A tiny, byte-deterministic raw disk image (``tiny_raw.dd``). It is committed to
  the repo (built once with :func:`build_tiny_raw_image`) so the suite needs no
  ``mkfs``/``mtools`` dependency in CI (01-RESEARCH.md Open Question A3).

* Tiny *filesystem* images for the Phase 2 walk — ext4, NTFS, FAT32 and a
  partitioned (FAT + ext4) image. Each is built once with the host ``mkfs.*`` /
  ``debugfs`` / ``mtools`` / ``sfdisk`` tools and **committed** under
  ``tests/fixtures/`` so CI never needs a privileged ``mkfs`` at test time
  (02-RESEARCH.md §Environment Availability, mirroring the ``tiny_raw.dd``
  approach). The exact ground-truth (file names, content, uid/gid/mode, the
  known deleted entry) is recorded as module constants below so the META tests
  can assert *exact* counts/values — the Nyquist "every file" signal.

* The malicious-archive builders consumed by the safe-extraction jail tests
  (plan 01-03): zip-slip, symlink-escape, device-file, ratio/size-bomb, and
  count-bomb. These are generated *programmatically at test time* and never
  shipped as live bombs (threat T-1-00-B). Every builder caps the size of what
  it generates so the builders themselves cannot exhaust resources.

Run as a script to (re)generate every committed image (needs the mkfs tools)::

    python tests/fixtures/make_fixtures.py
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Tiny raw image
# ---------------------------------------------------------------------------

# Kept well under 1 MB (01-RESEARCH.md A3). 64 KiB is plenty to prove read-only
# open + streaming-hash behaviour while staying tiny in the repo.
TINY_RAW_SIZE = 64 * 1024
TINY_RAW_NAME = "tiny_raw.dd"


def tiny_raw_bytes() -> bytes:
    """Return the deterministic byte content of the tiny raw image.

    The content is a fixed pseudo-random-looking but fully deterministic byte
    pattern (a simple LCG seeded by a constant), so the committed fixture and
    any regeneration are bit-identical and the image hashes reproducibly.

    Returns:
        Exactly :data:`TINY_RAW_SIZE` bytes.
    """
    out = bytearray(TINY_RAW_SIZE)
    # Linear congruential generator (glibc constants) — deterministic, no deps.
    state = 0x1234_5678
    for i in range(TINY_RAW_SIZE):
        state = (1103515245 * state + 12345) & 0x7FFF_FFFF
        out[i] = (state >> 16) & 0xFF
    return bytes(out)


def build_tiny_raw_image(dest: Path) -> Path:
    """Write the deterministic tiny raw image to ``dest``.

    Args:
        dest: Path to write the image to.

    Returns:
        The ``dest`` path.
    """
    dest.write_bytes(tiny_raw_bytes())
    return dest


# ---------------------------------------------------------------------------
# Tiny filesystem images (committed; built once with host mkfs tools)
# ---------------------------------------------------------------------------
#
# Ground-truth recorded as constants so the Phase 2 walk tests can assert EXACT
# counts/values (the "every file" Nyquist signal — 02-VALIDATION.md Sampling).
# Each FS holds one known regular file with known content + uid/gid/mode; the
# ext4 image additionally holds a *deleted* entry for the META-01 deleted-
# inventory test.

TINY_EXT4_NAME = "tiny_ext4.img"
TINY_NTFS_NAME = "tiny_ntfs.img"
TINY_FAT32_NAME = "tiny_fat32.img"
TINY_PARTITIONED_NAME = "tiny_partitioned.img"

# Known regular file written into every FS image.
FS_FILE_NAME = "file1.txt"
FS_FILE_CONTENT = b"pyautopsy fixture file one\n"

# ext4 second file that is created then deleted, leaving an UNALLOC entry whose
# inode/MFT addr the walk must still inventory (META-01 / D-18).
EXT4_DELETED_NAME = "deleted.txt"
EXT4_DELETED_CONTENT = b"this entry is deleted\n"

# Ground-truth ownership/mode applied to FS_FILE_NAME on ext4 via debugfs
# (META-03). FAT/NTFS have no real POSIX uid/gid; TSK reports 0 there.
EXT4_FILE_UID = 1000
EXT4_FILE_GID = 1000
EXT4_FILE_MODE = 0o644  # regular-file permission bits

# Image sizes. ext4/NTFS are happy small; FAT *32* needs >= ~33 MiB of clusters
# for mkfs.fat -F 32, so we use 64 MiB (02-RESEARCH Environment Availability).
_EXT4_SIZE = 1 * 1024 * 1024
_NTFS_SIZE = 2 * 1024 * 1024
_FAT32_SIZE = 64 * 1024 * 1024
_PART_FAT_SIZE = 64 * 1024 * 1024
_PART_EXT4_SIZE = 8 * 1024 * 1024


def _require_tool(name: str) -> str:
    """Return the path to ``name`` or raise an actionable error (build-time only)."""
    path = shutil.which(name)
    if path is None:
        raise RuntimeError(
            f"fixture build needs '{name}' but it is not on PATH. "
            "These images are committed to the repo precisely so CI never "
            "needs the mkfs tools; only re-run make_fixtures.py on a host that "
            "has them (Fedora: e2fsprogs/dosfstools/mtools/ntfs-3g/util-linux)."
        )
    return path


def _truncate(dest: Path, size: int) -> None:
    """Create a zero-filled sparse file of ``size`` bytes at ``dest``."""
    with open(dest, "wb") as fh:
        fh.truncate(size)


def build_tiny_ext4_image(dest: Path) -> Path:
    """Build a tiny ext4 image with one known file and one deleted entry.

    ``mkfs.ext4 -F`` formats a small backing file; ``debugfs -w`` then writes a
    known regular file (content + uid/gid/mode recorded above), creates a second
    file and ``rm``\\ s it so an UNALLOC/deleted entry survives for the META-01
    deleted-inventory test (D-18). The built image is committed; CI never runs
    ``mkfs`` (02-RESEARCH).
    """
    mkfs = _require_tool("mkfs.ext4")
    debugfs = _require_tool("debugfs")
    _truncate(dest, _EXT4_SIZE)
    # -F: force on a plain file; -q: quiet; -O ^... keeps the FS simple/portable.
    subprocess.run(
        [mkfs, "-F", "-q", "-b", "1024", str(dest)],
        check=True,
        capture_output=True,
    )
    with tempfile.TemporaryDirectory() as td:
        live = Path(td) / "live.bin"
        live.write_bytes(FS_FILE_CONTENT)
        deleted = Path(td) / "deleted.bin"
        deleted.write_bytes(EXT4_DELETED_CONTENT)
        # debugfs request file: write the live file (set uid/gid/mode), then
        # write + immediately rm the second file to leave a deleted entry.
        script = (
            f"write {live} {FS_FILE_NAME}\n"
            f"sif {FS_FILE_NAME} uid {EXT4_FILE_UID}\n"
            f"sif {FS_FILE_NAME} gid {EXT4_FILE_GID}\n"
            f"sif {FS_FILE_NAME} mode {EXT4_FILE_MODE:o}\n"
            f"write {deleted} {EXT4_DELETED_NAME}\n"
            f"rm {EXT4_DELETED_NAME}\n"
            "close\n"
        )
        subprocess.run(
            [debugfs, "-w", "-f", "/dev/stdin", str(dest)],
            input=script.encode(),
            check=True,
            capture_output=True,
        )
    return dest


def build_tiny_fat32_image(dest: Path) -> Path:
    """Build a tiny FAT32 image with one known file (FAT local-time test, D-16).

    ``mkfs.fat -F 32`` needs a reasonably large volume (>= ~33 MiB) so we use
    64 MiB; ``mcopy`` (mtools) writes the known file. ``MTOOLS_SKIP_CHECK=1``
    suppresses mtools' interactive geometry check. FAT stores *local* time with
    no embedded zone — the walk flags these ``local-time-inferred`` (D-16).
    """
    mkfs = _require_tool("mkfs.fat")
    mcopy = _require_tool("mcopy")
    _truncate(dest, _FAT32_SIZE)
    subprocess.run(
        [mkfs, "-F", "32", str(dest)], check=True, capture_output=True
    )
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / FS_FILE_NAME
        src.write_bytes(FS_FILE_CONTENT)
        env = {**os.environ, "MTOOLS_SKIP_CHECK": "1"}
        subprocess.run(
            [mcopy, "-i", str(dest), str(src), f"::{FS_FILE_NAME}"],
            check=True,
            capture_output=True,
            env=env,
        )
    return dest


def build_tiny_ntfs_image(dest: Path) -> Path:
    """Build a tiny NTFS image with one known file (mkntfs + ntfs mtools-free).

    ``mkntfs -F -Q`` does a fast, force format of a small backing file. NTFS
    times are UTC (unlike FAT); the file is written via ``ntfscp`` if present,
    otherwise the empty volume's system files still exercise the NTFS walk path.
    """
    mkntfs = _require_tool("mkntfs")
    _truncate(dest, _NTFS_SIZE)
    subprocess.run(
        [mkntfs, "-F", "-Q", "-s", "512", str(dest)],
        check=True,
        capture_output=True,
    )
    ntfscp = shutil.which("ntfscp")
    if ntfscp is not None:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / FS_FILE_NAME
            src.write_bytes(FS_FILE_CONTENT)
            subprocess.run(
                [ntfscp, str(dest), str(src), FS_FILE_NAME],
                check=True,
                capture_output=True,
            )
    return dest


def build_partitioned_image(dest: Path) -> Path:
    """Build a partitioned image: a FAT partition + an ext4 partition (D-15).

    Verifies the volume-offset path (02-RESEARCH Open Question A1): ``sfdisk``
    lays down a DOS partition table with two partitions, each formatted with a
    different filesystem so the walk must open each at ``part.start * block_size``
    and tag rows with the right ``volume_id``/offset.
    """
    sfdisk = _require_tool("sfdisk")
    mkfs_fat = _require_tool("mkfs.fat")
    mkfs_ext4 = _require_tool("mkfs.ext4")
    mcopy = _require_tool("mcopy")
    sector = 512
    fat_start = 2048  # sectors (1 MiB aligned)
    fat_sectors = _PART_FAT_SIZE // sector
    ext4_start = fat_start + fat_sectors
    ext4_sectors = _PART_EXT4_SIZE // sector
    total = (ext4_start + ext4_sectors + fat_start) * sector
    _truncate(dest, total)
    layout = (
        "label: dos\n"
        f"start={fat_start}, size={fat_sectors}, type=c\n"
        f"start={ext4_start}, size={ext4_sectors}, type=83\n"
    )
    subprocess.run(
        [sfdisk, str(dest)], input=layout.encode(), check=True, capture_output=True
    )
    with tempfile.TemporaryDirectory() as td:
        # Format the FAT partition in isolation, then dd it into place at offset.
        fat_img = Path(td) / "fat.part"
        _truncate(fat_img, _PART_FAT_SIZE)
        subprocess.run(
            [mkfs_fat, "-F", "32", str(fat_img)], check=True, capture_output=True
        )
        src = Path(td) / FS_FILE_NAME
        src.write_bytes(FS_FILE_CONTENT)
        env = {**os.environ, "MTOOLS_SKIP_CHECK": "1"}
        subprocess.run(
            [mcopy, "-i", str(fat_img), str(src), f"::{FS_FILE_NAME}"],
            check=True,
            capture_output=True,
            env=env,
        )
        ext4_img = Path(td) / "ext4.part"
        _truncate(ext4_img, _PART_EXT4_SIZE)
        subprocess.run(
            [mkfs_ext4, "-F", "-q", "-b", "1024", str(ext4_img)],
            check=True,
            capture_output=True,
        )
        # Splice each formatted partition into the whole-disk image at its offset.
        with open(dest, "r+b") as disk:
            disk.seek(fat_start * sector)
            disk.write(fat_img.read_bytes())
            disk.seek(ext4_start * sector)
            disk.write(ext4_img.read_bytes())
    return dest


# ---------------------------------------------------------------------------
# Malicious-archive builders (consumed by the safe_extract jail tests, plan 01-03)
# ---------------------------------------------------------------------------

# Caps so the builders themselves never become bombs (threat T-1-00-B).
_BOMB_FILLER_SIZE = 1 * 1024 * 1024  # 1 MiB of highly compressible zeros
_COUNT_BOMB_ENTRIES = 20_000


def build_zip_slip_tar(dest: Path) -> Path:
    """Build a tar whose member name escapes the destination (Zip Slip).

    The member name ``../../escape.txt`` must be REJECTED by the jail
    (``OutsideDestinationError`` under ``filter='data'``).
    """
    with tarfile.open(dest, "w") as tar:
        payload = b"escaped!\n"
        info = tarfile.TarInfo(name="../../escape.txt")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    return dest


def build_symlink_escape_tar(dest: Path) -> Path:
    """Build a tar containing an absolute symlink escape (``link -> /etc/passwd``).

    Must be REJECTED by the jail (``AbsoluteLinkError`` / special-file refusal).
    """
    with tarfile.open(dest, "w") as tar:
        info = tarfile.TarInfo(name="link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)
    return dest


def build_device_file_tar(dest: Path) -> Path:
    """Build a tar containing a character-device member.

    Must be REJECTED by the jail (``SpecialFileError`` under ``filter='data'``).
    """
    with tarfile.open(dest, "w") as tar:
        info = tarfile.TarInfo(name="dev/null")
        info.type = tarfile.CHRTYPE
        info.devmajor = 1
        info.devminor = 3
        tar.addfile(info)
    return dest


def build_ratio_bomb_zip(dest: Path) -> Path:
    """Build a zip with a tiny compressed / huge uncompressed ratio (size bomb).

    1 MiB of zeros compresses to a few hundred bytes — a high compression ratio
    the jail's ratio/size caps must REJECT. Capped at :data:`_BOMB_FILLER_SIZE`
    so the builder itself is bounded.
    """
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("bomb.bin", b"\x00" * _BOMB_FILLER_SIZE)
    return dest


def build_count_bomb_tar(dest: Path) -> Path:
    """Build a tar with a very large number of tiny members (count bomb).

    Exceeds a sane ``max_entries`` cap so the jail must REJECT on entry count.
    """
    with tarfile.open(dest, "w") as tar:
        empty = io.BytesIO(b"")
        for i in range(_COUNT_BOMB_ENTRIES):
            info = tarfile.TarInfo(name=f"f{i:06d}.txt")
            info.size = 0
            tar.addfile(info, empty)
    return dest


def main() -> None:
    """Regenerate every committed image next to this module (needs mkfs tools)."""
    here = Path(__file__).resolve().parent
    builders = (
        (TINY_RAW_NAME, build_tiny_raw_image),
        (TINY_EXT4_NAME, build_tiny_ext4_image),
        (TINY_NTFS_NAME, build_tiny_ntfs_image),
        (TINY_FAT32_NAME, build_tiny_fat32_image),
        (TINY_PARTITIONED_NAME, build_partitioned_image),
    )
    for name, build in builders:
        out = build(here / name)
        print(f"wrote {out} ({os.path.getsize(out)} bytes)")


if __name__ == "__main__":
    main()
