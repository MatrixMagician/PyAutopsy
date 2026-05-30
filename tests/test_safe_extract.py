"""Tests for the hardened ``safe_extract`` jail (INGEST-04, D-11).

Every malicious-archive fixture (zip-slip, symlink-escape, device-file,
ratio/size-bomb, count-bomb) must be REJECTED, and nothing may be written
outside the destination jail. Benign archives extract — but only into the jail.

The parametrized :func:`test_malicious_fixture_gate` is the Phase-1 security
completion gate referenced in 01-VALIDATION.md.
"""

from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from pyautopsy.util.safe_extract import (
    ExtractionLimits,
    ExtractionRejected,
    safe_extract,
)
from tests.fixtures import make_fixtures

# ---------------------------------------------------------------------------
# Local builders for cases not covered by the shared conftest fixtures.
# ---------------------------------------------------------------------------


def _build_zip_slip_zip(dest: Path) -> Path:
    """A zip whose member name escapes the destination (Zip Slip)."""
    with zipfile.ZipFile(dest, "w") as zf:
        zf.writestr("../../escape.txt", b"escaped!\n")
    return dest


def _build_absolute_tar(dest: Path) -> Path:
    """A tar with an absolute-path member (``/etc/cron.d/x``)."""
    with tarfile.open(dest, "w") as tar:
        payload = b"pwned\n"
        info = tarfile.TarInfo(name="/etc/cron.d/x")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    return dest


def _build_symlink_zip(dest: Path) -> Path:
    """A zip whose entry external-attr mode bits mark it a symlink."""
    with zipfile.ZipFile(dest, "w") as zf:
        info = zipfile.ZipInfo("link")
        # 0o120000 == S_IFLNK in the high 16 bits of external_attr.
        info.external_attr = (0o120777) << 16
        zf.writestr(info, "/etc/passwd")
    return dest


def _build_benign_tar(dest: Path) -> Path:
    """A well-formed benign tar with a couple of small regular files."""
    with tarfile.open(dest, "w") as tar:
        for name, data in (("a.txt", b"alpha\n"), ("sub/b.txt", b"beta\n")):
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return dest


def _build_benign_zip(dest: Path) -> Path:
    """A well-formed benign zip with a couple of small regular files."""
    with zipfile.ZipFile(dest, "w") as zf:
        zf.writestr("a.txt", b"alpha\n")
        zf.writestr("sub/b.txt", b"beta\n")
    return dest


def _no_escape(tmp_path: Path, jail: Path) -> bool:
    """True iff every file under tmp_path lives inside the jail dir."""
    jail_real = jail.resolve()
    for p in tmp_path.rglob("*"):
        if p.is_file() and not str(p.resolve()).startswith(str(jail_real)):
            # Allow the archive fixtures themselves (built into tmp_path root).
            if p.suffix in {".tar", ".zip"}:
                continue
            return False
    return True


# ---------------------------------------------------------------------------
# Task 1: path confinement, symlink/special refusal, name sanitization
# ---------------------------------------------------------------------------


def test_zip_slip_tar_rejected(zip_slip_tar: Path, tmp_path: Path) -> None:
    jail = tmp_path / "jail"
    with pytest.raises(ExtractionRejected):
        safe_extract(zip_slip_tar, jail)
    assert not (tmp_path / "escape.txt").exists()
    assert not (tmp_path.parent / "escape.txt").exists()
    assert _no_escape(tmp_path, jail)


def test_zip_slip_zip_rejected(tmp_path: Path) -> None:
    archive = _build_zip_slip_zip(tmp_path / "slip.zip")
    jail = tmp_path / "jail"
    with pytest.raises(ExtractionRejected):
        safe_extract(archive, jail)
    assert not (tmp_path / "escape.txt").exists()
    assert _no_escape(tmp_path, jail)


def test_symlink_escape_tar_rejected(
    symlink_escape_tar: Path, tmp_path: Path
) -> None:
    jail = tmp_path / "jail"
    with pytest.raises(ExtractionRejected):
        safe_extract(symlink_escape_tar, jail)
    assert not (jail / "link").is_symlink()
    assert _no_escape(tmp_path, jail)


def test_symlink_zip_rejected(tmp_path: Path) -> None:
    archive = _build_symlink_zip(tmp_path / "symlink.zip")
    jail = tmp_path / "jail"
    with pytest.raises(ExtractionRejected):
        safe_extract(archive, jail)
    assert not (jail / "link").is_symlink()
    assert _no_escape(tmp_path, jail)


def test_device_file_tar_rejected(device_file_tar: Path, tmp_path: Path) -> None:
    jail = tmp_path / "jail"
    with pytest.raises(ExtractionRejected):
        safe_extract(device_file_tar, jail)
    assert _no_escape(tmp_path, jail)


def test_absolute_path_tar_rejected(tmp_path: Path) -> None:
    archive = _build_absolute_tar(tmp_path / "absolute.tar")
    jail = tmp_path / "jail"
    with pytest.raises(ExtractionRejected):
        safe_extract(archive, jail)
    assert not Path("/etc/cron.d/x").exists()
    assert _no_escape(tmp_path, jail)


def test_benign_tar_extracts_into_jail(tmp_path: Path) -> None:
    archive = _build_benign_tar(tmp_path / "benign.tar")
    jail = tmp_path / "jail"
    result = safe_extract(archive, jail)
    assert (jail / "a.txt").read_bytes() == b"alpha\n"
    assert (jail / "sub" / "b.txt").read_bytes() == b"beta\n"
    jail_real = jail.resolve()
    for written in result.extracted:
        assert str(written.resolve()).startswith(str(jail_real))
    assert _no_escape(tmp_path, jail)


def test_benign_zip_extracts_into_jail(tmp_path: Path) -> None:
    archive = _build_benign_zip(tmp_path / "benign.zip")
    jail = tmp_path / "jail"
    safe_extract(archive, jail)
    assert (jail / "a.txt").read_bytes() == b"alpha\n"
    assert (jail / "sub" / "b.txt").read_bytes() == b"beta\n"
    assert _no_escape(tmp_path, jail)


def test_original_member_name_preserved_as_metadata(tmp_path: Path) -> None:
    """On-disk name is sanitized; original member name kept as evidence."""
    weird = "weird\x01name\tfile.txt"
    archive = tmp_path / "weird.tar"
    with tarfile.open(archive, "w") as tar:
        payload = b"data\n"
        info = tarfile.TarInfo(name=weird)
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    jail = tmp_path / "jail"
    result = safe_extract(archive, jail)
    # The original (control-char) name is preserved in the returned metadata.
    originals = [m.original_name for m in result.members]
    assert weird in originals
    # No file with raw control chars was written; everything stays in the jail.
    assert _no_escape(tmp_path, jail)


def test_one_malformed_member_does_not_abort_benign_members(
    tmp_path: Path,
) -> None:
    """A traversal member is skipped/recorded; a benign sibling still extracts."""
    archive = tmp_path / "mixed.tar"
    with tarfile.open(archive, "w") as tar:
        good = b"good\n"
        ginfo = tarfile.TarInfo(name="good.txt")
        ginfo.size = len(good)
        tar.addfile(ginfo, io.BytesIO(good))
        bad = b"bad\n"
        binfo = tarfile.TarInfo(name="../escape.txt")
        binfo.size = len(bad)
        tar.addfile(binfo, io.BytesIO(bad))
    jail = tmp_path / "jail"
    result = safe_extract(archive, jail, on_member_error="skip")
    assert (jail / "good.txt").read_bytes() == b"good\n"
    assert result.rejected  # the bad member was recorded as rejected
    assert _no_escape(tmp_path, jail)


# ---------------------------------------------------------------------------
# Task 2: decompression-bomb caps
# ---------------------------------------------------------------------------


def test_total_uncompressed_cap_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "total.tar"
    with tarfile.open(archive, "w") as tar:
        chunk = b"\x00" * (64 * 1024)
        for i in range(4):
            info = tarfile.TarInfo(name=f"f{i}.bin")
            info.size = len(chunk)
            tar.addfile(info, io.BytesIO(chunk))
    jail = tmp_path / "jail"
    limits = ExtractionLimits(max_total_uncompressed=100 * 1024)
    with pytest.raises(ExtractionRejected):
        safe_extract(archive, jail, limits=limits)
    assert _no_escape(tmp_path, jail)


def test_per_entry_size_cap_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "entry.tar"
    with tarfile.open(archive, "w") as tar:
        payload = b"\x00" * (200 * 1024)
        info = tarfile.TarInfo(name="big.bin")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    jail = tmp_path / "jail"
    limits = ExtractionLimits(max_entry_size=100 * 1024)
    with pytest.raises(ExtractionRejected):
        safe_extract(archive, jail, limits=limits)
    assert _no_escape(tmp_path, jail)


def test_ratio_bomb_zip_rejected(ratio_bomb_zip: Path, tmp_path: Path) -> None:
    jail = tmp_path / "jail"
    with pytest.raises(ExtractionRejected):
        safe_extract(ratio_bomb_zip, jail)
    assert _no_escape(tmp_path, jail)


def test_ratio_bomb_tar_rejected(tmp_path: Path) -> None:
    """A highly compressible tar.gz trips the archive-scope ratio cap (WR-03)."""
    # Gzip-compressed tar; the .tar suffix keeps _no_escape's archive allowance
    # working (it ignores .tar/.zip fixtures), and tarfile detects gzip by
    # content regardless of the name.
    archive = tmp_path / "ratio.tar"
    # 4 MiB of zeros compresses to a few KiB — an enormous ratio.
    payload = b"\x00" * (4 * 1024 * 1024)
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo(name="bomb.bin")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    jail = tmp_path / "jail"
    # Per-entry and total caps are generous; only the ratio guard should fire.
    limits = ExtractionLimits(
        max_entry_size=64 * 1024 * 1024,
        max_total_uncompressed=64 * 1024 * 1024,
        max_ratio=10,
    )
    with pytest.raises(ExtractionRejected, match="compression-ratio"):
        safe_extract(archive, jail, limits=limits)
    assert _no_escape(tmp_path, jail)


def test_benign_normalizable_tar_name_not_false_rejected(tmp_path: Path) -> None:
    """A benign member whose name the data filter normalizes still extracts (WR-04)."""
    archive = tmp_path / "norm.tar"
    payload = b"alpha\n"
    with tarfile.open(archive, "w") as tar:
        # `a//b.txt` is benign but the data filter collapses the double slash;
        # a raw-equality escape check would false-reject it.
        info = tarfile.TarInfo(name="a//b.txt")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    jail = tmp_path / "jail"
    result = safe_extract(archive, jail)
    assert not result.rejected
    assert (jail / "a" / "b.txt").read_bytes() == payload
    assert _no_escape(tmp_path, jail)


def test_count_bomb_tar_rejected(count_bomb_tar: Path, tmp_path: Path) -> None:
    jail = tmp_path / "jail"
    with pytest.raises(ExtractionRejected):
        safe_extract(count_bomb_tar, jail)
    assert _no_escape(tmp_path, jail)


def test_total_cap_aborts_before_full_bomb_written(tmp_path: Path) -> None:
    """The running byte counter aborts mid-stream — not the whole bomb on disk."""
    archive = tmp_path / "stream.tar"
    entry_size = 512 * 1024
    with tarfile.open(archive, "w") as tar:
        for i in range(8):
            payload = b"\x00" * entry_size
            info = tarfile.TarInfo(name=f"f{i}.bin")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    jail = tmp_path / "jail"
    limits = ExtractionLimits(max_total_uncompressed=entry_size)
    with pytest.raises(ExtractionRejected):
        safe_extract(archive, jail, limits=limits)
    written = sum(p.stat().st_size for p in jail.rglob("*") if p.is_file())
    # Less than the full 8-entry bomb (4 MiB) made it to disk.
    assert written < 8 * entry_size


def test_limits_defaults_match_documented_values() -> None:
    limits = ExtractionLimits()
    assert limits.max_total_uncompressed == 1 * 1024 * 1024 * 1024
    assert limits.max_entry_size == 256 * 1024 * 1024
    assert limits.max_ratio == 100
    assert limits.max_entries == 10_000
    assert limits.max_depth == 3


def test_limits_are_overridable() -> None:
    limits = ExtractionLimits(max_entries=5, max_ratio=10)
    assert limits.max_entries == 5
    assert limits.max_ratio == 10


# ---------------------------------------------------------------------------
# Phase-1 security completion gate: every malicious fixture is REJECTED.
# ---------------------------------------------------------------------------

# (builder, on-disk suffix) per malicious fixture.
_GATE_BUILDERS = {
    "zip-slip-tar": (make_fixtures.build_zip_slip_tar, ".tar"),
    "zip-slip-zip": (_build_zip_slip_zip, ".zip"),
    "symlink-escape": (make_fixtures.build_symlink_escape_tar, ".tar"),
    "device-file": (make_fixtures.build_device_file_tar, ".tar"),
    "ratio-bomb": (make_fixtures.build_ratio_bomb_zip, ".zip"),
    "count-bomb": (make_fixtures.build_count_bomb_tar, ".tar"),
}


@pytest.mark.parametrize("name", sorted(_GATE_BUILDERS))
def test_malicious_fixture_gate(name: str, tmp_path: Path) -> None:
    """D-11 phase-completion gate: each hostile input REJECTED, no jail escape."""
    builder, suffix = _GATE_BUILDERS[name]
    archive = builder(tmp_path / f"{name}{suffix}")
    jail = tmp_path / "jail"
    with pytest.raises(ExtractionRejected):
        safe_extract(archive, jail)
    assert _no_escape(tmp_path, jail)
