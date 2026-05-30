"""Deterministic builders for test evidence and malicious-archive fixtures.

Two kinds of fixture are produced here:

* A tiny, byte-deterministic raw disk image (``tiny_raw.dd``). It is committed to
  the repo (built once with :func:`build_tiny_raw_image`) so the suite needs no
  ``mkfs``/``mtools`` dependency in CI (01-RESEARCH.md Open Question A3).

* The malicious-archive builders consumed by the safe-extraction jail tests
  (plan 01-03): zip-slip, symlink-escape, device-file, ratio/size-bomb, and
  count-bomb. These are generated *programmatically at test time* and never
  shipped as live bombs (threat T-1-00-B). Every builder caps the size of what
  it generates so the builders themselves cannot exhaust resources.

Run as a script to (re)generate the committed image::

    python tests/fixtures/make_fixtures.py
"""

from __future__ import annotations

import io
import os
import tarfile
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
    """Regenerate the committed tiny raw image next to this module."""
    here = Path(__file__).resolve().parent
    out = build_tiny_raw_image(here / TINY_RAW_NAME)
    print(f"wrote {out} ({os.path.getsize(out)} bytes)")


if __name__ == "__main__":
    main()
