"""Tests for the integrity layer (INGEST-02) — single-pass hashing + compare.

Proves the streaming MD5 + SHA-256 pass equals a ``hashlib`` reference over the
same bytes (one pass, configurable chunk), that ``verify_acquisition`` reports
PASS/FAIL with case-insensitive hex compare and surfaces FAIL as a loud,
non-zero-exit-worthy error, and that ``reverify`` raises on an altered baseline
(end-of-run re-verification semantics).

The hasher is exercised both against the real ``tiny_raw.dd`` fixture (via the
native seam) and against an in-memory fake handle, keeping the integrity tier
unit-testable with no real image (D-06).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from pyautopsy.evidence.image import open_image
from pyautopsy.evidence.integrity import (
    IntegrityError,
    MountedSourceError,
    VerifyResult,
    assert_source_not_mounted,
    hash_file,
    hash_image,
    reverify,
    verify_acquisition,
)


class _FakeImage:
    """An in-memory ``read(offset, size)`` / ``get_size()`` byte source."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self, offset: int, size: int) -> bytes:
        return self._data[offset : offset + size]

    def get_size(self) -> int:
        return len(self._data)


class _TruncatedImage:
    """A source whose ``get_size()`` over-reports the retrievable bytes.

    Models a truncated/corrupt acquisition: ``read`` returns ``b""`` (EOF)
    once the real bytes are exhausted, before ``offset`` reaches ``total``.
    """

    def __init__(self, data: bytes, reported_size: int) -> None:
        self._data = data
        self._reported_size = reported_size

    def read(self, offset: int, size: int) -> bytes:
        return self._data[offset : offset + size]

    def get_size(self) -> int:
        return self._reported_size


def test_hash_image_matches_hashlib_reference() -> None:
    """Single-pass md5+sha256 equals a hashlib reference over the same bytes."""
    data = bytes(range(256)) * 97  # 24 832 bytes, spans several chunks
    handle = _FakeImage(data)

    result = hash_image(handle, chunk=1024)

    assert result["md5"] == hashlib.md5(data).hexdigest()
    assert result["sha256"] == hashlib.sha256(data).hexdigest()


def test_hash_image_default_chunk_matches() -> None:
    """The default chunk size produces the same digests as a reference."""
    data = b"forensic-soundness" * 1000
    result = hash_image(_FakeImage(data))
    assert result["sha256"] == hashlib.sha256(data).hexdigest()


def test_hash_image_empty_source() -> None:
    """An empty source yields the digests of the empty byte string."""
    result = hash_image(_FakeImage(b""))
    assert result["md5"] == hashlib.md5(b"").hexdigest()
    assert result["sha256"] == hashlib.sha256(b"").hexdigest()


def test_hash_image_over_real_fixture(tiny_raw_image: Path) -> None:
    """Hashing via the native seam equals a direct hashlib pass over the file."""
    expected = hashlib.sha256(tiny_raw_image.read_bytes()).hexdigest()
    with open_image(tiny_raw_image) as handle:
        result = hash_image(handle)
    assert result["sha256"] == expected


@pytest.mark.parametrize("chunk", [1, 7, 512, 4096, 1 << 20])
def test_hash_image_chunk_invariant(chunk: int) -> None:
    """The digest is independent of the streaming chunk size."""
    data = b"\x00\x01\x02\x03\x04\x05\x06\x07" * 513
    result = hash_image(_FakeImage(data), chunk=chunk)
    assert result["sha256"] == hashlib.sha256(data).hexdigest()


def test_hash_image_short_read_raises_loudly() -> None:
    """A source that short-reads vs get_size() fails — no partial digest (CR-02)."""
    # 100 real bytes but get_size() claims 1000: read() EOFs at offset 100.
    handle = _TruncatedImage(b"\x00" * 100, reported_size=1000)
    with pytest.raises(IntegrityError, match="short read"):
        hash_image(handle)


def test_short_read_policies_diverge_between_image_and_file() -> None:
    """The two callers of the shared digest loop keep opposite short-read policies.

    ``hash_image`` and ``hash_file`` stream through one chunked-digest routine,
    but what they do when the source runs out early must stay different, and
    the sharing is what makes that fragile:

    * a short *image* read is a hard integrity failure — a digest must never
      silently cover less than the whole acquisition, so it raises and records
      nothing (INGEST-02/D-08);
    * a short *file* read is a skip — the walk records null hashes plus a
      reason and carries on rather than aborting the whole inventory over one
      unreadable entry (D-17).

    Both uphold the same underlying rule: a partial digest is never returned.
    """
    truncated = _TruncatedImage(b"\x00" * 100, reported_size=1000)
    with pytest.raises(IntegrityError, match="short read"):
        hash_image(truncated)

    def short_reader(offset: int, size: int) -> bytes:
        """Yield only the first 100 bytes, then EOF — the file's `_TruncatedImage`."""
        available = max(0, 100 - offset)
        return b"\x00" * min(size, available)

    assert hash_file(short_reader, 1000) is None


def test_shared_digest_loop_is_chunk_invariant_for_files() -> None:
    """Per-file digests do not depend on the chunk size the loop reads in."""
    data = bytes(range(256)) * 41
    reference = {
        "md5": hashlib.md5(data).hexdigest(),
        "sha1": hashlib.sha1(data).hexdigest(),
        "sha256": hashlib.sha256(data).hexdigest(),
    }

    def reader(offset: int, size: int) -> bytes:
        return data[offset : offset + size]

    for chunk in (1, 7, 512, 4096, 1 << 20):
        assert hash_file(reader, len(data), chunk=chunk) == reference


def test_reverify_short_read_raises_loudly() -> None:
    """Re-verify over a now-truncated source fails loud, not a false PASS (CR-02)."""
    handle = _TruncatedImage(b"\x00" * 100, reported_size=1000)
    baseline = {"sha256": "0" * 64, "md5": "0" * 32}
    with pytest.raises(IntegrityError, match="short read"):
        reverify(handle, baseline)


def test_verify_acquisition_pass_sha256() -> None:
    """A matching supplied SHA-256 (any case) returns PASS."""
    data = b"acquired bytes"
    computed = hash_image(_FakeImage(data))
    supplied = computed["sha256"].upper()  # case-insensitive compare
    result = verify_acquisition(computed, supplied)
    assert isinstance(result, VerifyResult)
    assert result.passed is True
    assert result.algorithm == "sha256"


def test_verify_acquisition_pass_md5() -> None:
    """A supplied MD5 is matched against the computed MD5."""
    data = b"acquired bytes"
    computed = hash_image(_FakeImage(data))
    result = verify_acquisition(computed, computed["md5"])
    assert result.passed is True
    assert result.algorithm == "md5"


def test_verify_acquisition_fail_is_loud() -> None:
    """A mismatching supplied hash returns FAIL exposed as a loud failure."""
    computed = hash_image(_FakeImage(b"real bytes"))
    bad = "0" * 64  # well-formed sha256 length but wrong value
    result = verify_acquisition(computed, bad)
    assert result.passed is False
    # FAIL must be representable as a loud, non-zero-exit-worthy error.
    with pytest.raises(IntegrityError):
        result.raise_for_status()


def test_verify_acquisition_unknown_length_raises() -> None:
    """A supplied hash matching no known algorithm length raises clearly."""
    computed = hash_image(_FakeImage(b"x"))
    with pytest.raises(IntegrityError):
        verify_acquisition(computed, "deadbeef")


def test_verify_acquisition_non_hex_right_length_raises() -> None:
    """A right-length but non-hex hash is rejected as malformed, not FAIL (WR-07)."""
    computed = hash_image(_FakeImage(b"x"))
    not_hex = "z" * 64  # correct sha256 length, but not hexadecimal
    with pytest.raises(IntegrityError, match="hexadecimal"):
        verify_acquisition(computed, not_hex)


# -- mounted-source guard: non-ASCII mountpoint decode (CR-01) -------------


def test_assert_source_not_mounted_matches_non_ascii_mountpoint(
    tmp_path: Path,
) -> None:
    """A non-ASCII mountpoint must still match and refuse the source (CR-01)."""
    source = tmp_path / "café"
    source.mkdir()
    real = source.resolve()
    # /proc/mounts emits the mountpoint field; non-ASCII bytes are verbatim.
    mounts_text = f"/dev/sdb1 {real} ext4 rw,relatime 0 0\n"
    with pytest.raises(MountedSourceError):
        assert_source_not_mounted(source, mounts_text=mounts_text)


def test_assert_source_not_mounted_decodes_octal_escapes(
    tmp_path: Path,
) -> None:
    """An octal-escaped space in the mountpoint field is decoded correctly."""
    source = tmp_path / "mnt point"  # contains a space
    source.mkdir()
    real = str(source.resolve())
    escaped = real.replace(" ", r"\040")
    mounts_text = f"/dev/sdb1 {escaped} ext4 rw,relatime 0 0\n"
    with pytest.raises(MountedSourceError):
        assert_source_not_mounted(source, mounts_text=mounts_text)


def test_assert_source_not_mounted_allows_non_mount_path(
    tmp_path: Path,
) -> None:
    """An ordinary path that is not a mountpoint is permitted."""
    source = tmp_path / "café" / "image.dd"
    source.parent.mkdir()
    source.write_bytes(b"data")
    mounts_text = "/dev/sda1 / ext4 rw 0 0\n"
    # Must not raise — the source is not itself a mountpoint.
    assert_source_not_mounted(source, mounts_text=mounts_text)


def test_reverify_passes_on_unchanged_source() -> None:
    """Re-hashing an unchanged source against its baseline does not raise."""
    handle = _FakeImage(b"unchanged evidence bytes")
    baseline = hash_image(handle)
    reverify(handle, baseline)  # must not raise


def test_reverify_raises_on_altered_baseline() -> None:
    """An end-of-run mismatch (tampered baseline) fails loudly."""
    handle = _FakeImage(b"evidence bytes")
    baseline = hash_image(handle)
    tampered = {**baseline, "sha256": "0" * 64}
    with pytest.raises(IntegrityError):
        reverify(handle, tampered)


def test_chunk_validation_precedes_any_evidence_read() -> None:
    """A bad chunk size is a caller error, reported before the source is touched.

    Both hashers validate before reading. Otherwise an unreadable source would
    surface its read failure first, and the caller would be told the evidence is
    broken when in fact the call was.
    """

    class ExplodingSource:
        """Fails on any access, so a read before validation is unmistakable."""

        def read(self, offset: int, size: int) -> bytes:
            raise AssertionError("source was read before the chunk was validated")

        def get_size(self) -> int:
            raise AssertionError("source was sized before the chunk was validated")

    with pytest.raises(ValueError, match="chunk must be positive"):
        hash_image(ExplodingSource(), chunk=0)

    def exploding_reader(offset: int, size: int) -> bytes:
        raise AssertionError("content was read before the chunk was validated")

    with pytest.raises(ValueError, match="chunk must be positive"):
        hash_file(exploding_reader, 10, chunk=-1)
