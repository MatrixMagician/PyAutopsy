"""Integrity layer — single-pass hashing, acquisition compare, re-verify, guards.

This module is pure Python (no native imports): it streams **MD5 + SHA-256 in a
single pass** over any object exposing ``read(offset, size)`` / ``get_size()``
(D-07), so it works identically over a raw ``pytsk3.Img_Info`` and the
:class:`~pyautopsy.evidence.image.EWFImgInfo` adapter and is unit-testable with
an in-memory fake (D-06).

It provides the three forensic-integrity controls from INGEST-02 / INGEST-03 and
D-08:

* :func:`hash_image` — one streaming pass computing both digests.
* :func:`verify_acquisition` — compare the computed hash against a supplied
  acquisition hash (case-insensitive hex), returning a :class:`VerifyResult`
  whose FAIL is a loud, non-zero-exit-worthy :class:`IntegrityError`.
* :func:`reverify` — recompute at end of run and raise on any drift from the
  ingest-time baseline.

Plus the read-only boundary guard :func:`assert_source_not_mounted`
(PITFALLS P1, ASVS V4): there is **no write/mount/losetup path to the source**
anywhere in this module; the only thing it does to the source is read it.

SHA-256 is the forensic primary. MD5 is retained for legacy hash-set / EWF
interop only and is **NOT** relied upon for tamper-evidence (ASVS V6).
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

__all__ = [
    "EMPTY",
    "IntegrityError",
    "MountedSourceError",
    "VerifyResult",
    "assert_source_not_mounted",
    "hash_file",
    "hash_image",
    "reverify",
    "verify_acquisition",
]

# Default streaming chunk: 8 MiB — memory-bounded for multi-GB images while
# keeping read syscall overhead low (D-07, configurable).
_DEFAULT_CHUNK = 8 * 1024 * 1024

# Per-file streaming chunk: 1 MiB — memory-bounded for the many smaller reads of
# a filesystem walk while keeping the single-pass shape (D-17, configurable).
_DEFAULT_FILE_CHUNK = 1 * 1024 * 1024

# The well-known empty-file digests (MD5/SHA-1/SHA-256 of zero bytes). Returned
# verbatim for a zero-length file so the no-content case is recorded as a
# defensible, reproducible sentinel rather than skipped (D-17). These are the
# digests of ``b""`` and are asserted against a live ``hashlib`` pass in tests.
EMPTY: dict[str, str] = {
    "md5": "d41d8cd98f00b204e9800998ecf8427e",
    "sha1": "da39a3ee5e6b4b0d3255bfef95601890afd80709",
    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
}

# Map a supplied hex-digest length to the algorithm it identifies.
_LEN_TO_ALGO: dict[int, str] = {32: "md5", 64: "sha256"}

# /proc/mounts escapes a handful of bytes in the mountpoint field as a
# three-digit octal sequence (``\040`` space, ``\011`` tab, ``\012`` newline,
# ``\134`` backslash). We unescape ONLY these octal sequences on the raw bytes
# and then decode the result as UTF-8 — never routing UTF-8 through
# ``unicode_escape`` (a Latin-1 codec that corrupts multi-byte mountpoints and
# silently defeats the guard for non-ASCII paths).
_OCTAL_ESCAPE = re.compile(rb"\\([0-7]{3})")


class IntegrityError(Exception):
    """Raised when an integrity check fails (acquisition mismatch or re-verify).

    This is the loud, non-zero-exit-worthy failure the orchestrator turns into a
    failed run and an audit FAIL event (D-08). It is deliberately a hard error,
    not a warning: a hash mismatch means the evidence cannot be trusted.
    """


class MountedSourceError(Exception):
    """Raised when the evidence source path is (under) a mounted filesystem.

    Operating on a mounted source risks journal replay, atime updates, and mount
    counter bumps — all evidence-altering side effects (PITFALLS P1). The tool
    refuses to proceed.
    """


class ReadableSource(Protocol):
    """The minimal byte-source interface :func:`hash_image` consumes."""

    def read(self, offset: int, size: int) -> bytes:
        """Read ``size`` bytes starting at ``offset``."""

    def get_size(self) -> int:
        """Return the total size in bytes."""


class ContentReader(Protocol):
    """A read-only ``(offset, size) -> bytes`` callable :func:`hash_file` consumes.

    Implemented by the FS seam as a thin closure over the TSK ``File.read_random``
    so ``hash_file`` never sees a native object and this module stays native-free
    (D-14) and testable with a plain ``lambda offset, size: b"..."`` (D-06).
    """

    def __call__(self, offset: int, size: int) -> bytes:  # pragma: no cover - Protocol
        """Read ``size`` content bytes starting at ``offset`` (read-only)."""
        ...


@dataclass(frozen=True, slots=True)
class VerifyResult:
    """Outcome of comparing a computed hash against a supplied acquisition hash.

    Attributes:
        passed: ``True`` if the supplied hash matched the computed digest.
        algorithm: The algorithm compared (``"md5"`` or ``"sha256"``).
        computed: The computed hex digest for ``algorithm``.
        supplied: The supplied hex digest (normalised to lowercase).
    """

    passed: bool
    algorithm: str
    computed: str
    supplied: str

    def raise_for_status(self) -> None:
        """Raise :class:`IntegrityError` if the comparison FAILED.

        Raises:
            IntegrityError: If :attr:`passed` is ``False``. The message names the
                algorithm and both digests so the failure is fully audit-able.
        """
        if not self.passed:
            raise IntegrityError(
                f"acquisition hash mismatch ({self.algorithm}): "
                f"computed {self.computed}, supplied {self.supplied}"
            )


def hash_image(
    source: ReadableSource, chunk: int = _DEFAULT_CHUNK
) -> dict[str, str]:
    """Compute MD5 + SHA-256 over a byte source in a single streaming pass.

    One pass updates both digests, so the source is read exactly once regardless
    of how many algorithms are computed (D-07; never two passes). Works for raw
    and E01 alike because both expose ``read(offset, size)``.

    Args:
        source: A byte source exposing ``read(offset, size)`` and ``get_size()``.
        chunk: Streaming chunk size in bytes. Must be positive.

    Returns:
        A mapping ``{"md5": <hex>, "sha256": <hex>}``.

    Raises:
        ValueError: If ``chunk`` is not positive.
        IntegrityError: If the source short-reads — fewer bytes are retrievable
            than ``get_size()`` reports (a truncated/corrupt acquisition). A
            digest must never silently cover less than the whole image
            (INGEST-02/D-08), so a short read is a loud failure.
    """
    if chunk <= 0:
        raise ValueError(f"chunk must be positive, got {chunk}")

    md5 = hashlib.md5()
    sha256 = hashlib.sha256()
    total = source.get_size()
    offset = 0
    while offset < total:
        want = min(chunk, total - offset)
        block = source.read(offset, want)
        if not block:
            break
        md5.update(block)
        sha256.update(block)
        offset += len(block)
    if offset != total:
        raise IntegrityError(
            f"short read while hashing source: read {offset} of {total} bytes "
            "(image truncated or unreadable); refusing to record a partial "
            "digest"
        )
    return {"md5": md5.hexdigest(), "sha256": sha256.hexdigest()}


def hash_file(
    read_random: ContentReader,
    size: int,
    *,
    chunk: int = _DEFAULT_FILE_CHUNK,
    max_size: int | None = None,
) -> dict[str, str] | None:
    """Compute MD5 + SHA-1 + SHA-256 over one file in a single streaming pass.

    The per-file analogue of :func:`hash_image` (D-07/D-17): one ``while`` loop
    updates all three digests, so the file's content is read exactly once. The
    bytes come from a ``read_random(offset, size) -> bytes`` callable — the FS
    seam's read-only byte-reader closure over the TSK ``File`` (D-05/P1) — so this
    module stays native-free (D-14) and unit-testable with a plain ``lambda``.

    SHA-256 is the forensic primary; MD5 and SHA-1 are retained for NSRL / legacy
    hash-set interop only and are **NOT** relied upon for tamper-evidence
    (CLAUDE.md, ASVS V6).

    Unlike :func:`hash_image` (which raises on a short read because a partial
    *image* digest is never acceptable), the per-file path treats a short read as
    a non-fatal skip — it returns ``None`` so the caller records null hashes plus
    a reason and continues the walk, rather than aborting the whole inventory over
    one unreadable/truncated entry. The no-partial-digest principle is preserved
    either way: a partial digest is never returned.

    Args:
        read_random: A read-only ``(offset, size) -> bytes`` callable yielding the
            file's content bytes (the FS seam wraps the TSK ``File.read_random``).
        size: The file's logical size in bytes (``0`` ⇒ empty-file sentinel).
        chunk: Streaming chunk size in bytes. Must be positive.
        max_size: If set and ``size`` exceeds it, the file is skipped (returns
            ``None``) — the DoS guard for a crafted huge logical size (D-17,
            threat T-2-03-HOG). ``None`` (default) means no cap.

    Returns:
        A mapping ``{"md5", "sha1", "sha256"}`` of hex digests; a copy of
        :data:`EMPTY` for a zero-length file; or ``None`` when the file is skipped
        for size or short-reads (no partial digest is ever returned).

    Raises:
        ValueError: If ``chunk`` is not positive.
    """
    if chunk <= 0:
        raise ValueError(f"chunk must be positive, got {chunk}")
    if size == 0:
        return dict(EMPTY)
    if max_size is not None and size > max_size:
        return None  # skipped: caller records null hashes + an oversize reason.

    md5 = hashlib.md5()
    sha1 = hashlib.sha1()
    sha256 = hashlib.sha256()
    off = 0
    while off < size:
        want = min(chunk, size - off)
        block = read_random(off, want)
        if not block:
            break
        md5.update(block)
        sha1.update(block)
        sha256.update(block)
        off += len(block)
    if off != size:
        # Short/truncated read: do NOT record a partial digest (no-partial-digest
        # principle). Per-file divergence from hash_image — skip, do not raise.
        return None
    return {
        "md5": md5.hexdigest(),
        "sha1": sha1.hexdigest(),
        "sha256": sha256.hexdigest(),
    }


def verify_acquisition(computed: dict[str, str], supplied: str) -> VerifyResult:
    """Compare a computed digest against a supplied acquisition hash.

    The supplied hash is matched (case-insensitively) against the computed digest
    of the algorithm identified by the supplied hash's hex length (32 → MD5,
    64 → SHA-256). A mismatch returns a FAIL :class:`VerifyResult`; the caller
    turns FAIL into a loud, non-zero-exit failure via
    :meth:`VerifyResult.raise_for_status` (D-08).

    Args:
        computed: The digests from :func:`hash_image`.
        supplied: The examiner-supplied acquisition hash (hex; any case).

    Returns:
        A :class:`VerifyResult` describing PASS/FAIL for the matched algorithm.

    Raises:
        IntegrityError: If ``supplied`` has no recognised digest length (i.e. it
            matches neither MD5 nor SHA-256), or is not valid hexadecimal, so it
            cannot be compared at all. Only md5/sha256 acquisition hashes are
            accepted; a malformed input is rejected as malformed rather than
            silently treated as a mismatch.
    """
    normalised = supplied.strip().lower()
    algorithm = _LEN_TO_ALGO.get(len(normalised))
    if algorithm is None or algorithm not in computed:
        raise IntegrityError(
            f"supplied acquisition hash is not a recognised md5/sha256 hex "
            f"digest (length {len(normalised)}): {supplied!r}"
        )
    try:
        int(normalised, 16)
    except ValueError as exc:
        raise IntegrityError(
            f"supplied acquisition hash is not valid hexadecimal: "
            f"{supplied!r}"
        ) from exc
    computed_digest = computed[algorithm].lower()
    return VerifyResult(
        passed=computed_digest == normalised,
        algorithm=algorithm,
        computed=computed_digest,
        supplied=normalised,
    )


def reverify(source: ReadableSource, baseline: dict[str, str]) -> None:
    """Re-hash the source and assert it still matches the ingest-time baseline.

    Called at end of run: re-streams the source and compares both digests to the
    baseline captured at ingest. Any drift means the source changed (or the
    baseline was tampered with) and is a loud failure (INGEST-03 / D-08).

    Args:
        source: The same byte source hashed at ingest.
        baseline: The ingest-time digests from :func:`hash_image`.

    Raises:
        IntegrityError: If any recomputed digest differs from the baseline.
    """
    current = hash_image(source)
    mismatches = [
        algo
        for algo in ("sha256", "md5")
        if algo in baseline and current.get(algo) != baseline[algo]
    ]
    if mismatches:
        details = ", ".join(
            f"{algo}: baseline {baseline[algo]} != recomputed {current.get(algo)}"
            for algo in mismatches
        )
        raise IntegrityError(
            f"end-of-run re-verification failed — source hash changed ({details})"
        )


def _read_proc_mounts() -> str:
    """Return the contents of ``/proc/mounts`` (empty string if unavailable)."""
    try:
        return Path("/proc/mounts").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _unescape_mount_field(field: str) -> str:
    """Decode a ``/proc/mounts`` field's octal escapes back to a real path.

    The kernel escapes only space/tab/newline/backslash as three-digit octal
    sequences (e.g. ``\\040`` → space); all other bytes — including multi-byte
    UTF-8 — are emitted verbatim. We therefore unescape ONLY those octal
    sequences on the raw bytes, then decode the result as UTF-8. This is the
    fix for the ``unicode_escape`` mis-decode that corrupted every non-ASCII
    mountpoint and let a mounted evidence path bypass the P1 guard.

    Args:
        field: The raw mountpoint field as split from a ``/proc/mounts`` line.

    Returns:
        The decoded mountpoint path with octal escapes resolved.
    """
    raw = field.encode("utf-8")
    raw = _OCTAL_ESCAPE.sub(lambda m: bytes([int(m.group(1), 8)]), raw)
    return raw.decode("utf-8", errors="surrogateescape")


def _mountpoints(mounts_text: str) -> list[str]:
    """Parse mountpoint paths from ``/proc/mounts``-formatted text.

    Field 2 of each line is the mountpoint, with octal escapes for spaces etc.
    """
    points: list[str] = []
    for line in mounts_text.splitlines():
        fields = line.split()
        if len(fields) < 2:
            continue
        mountpoint = _unescape_mount_field(fields[1])
        points.append(os.path.realpath(mountpoint))
    return points


def assert_source_not_mounted(
    path: str | os.PathLike[str], mounts_text: str | None = None
) -> None:
    """Refuse a source path that is itself a mounted filesystem (P1).

    The actionable mounted-source case is the examiner pointing the tool at a
    **mounted evidence filesystem** — e.g. a loop-mounted image — rather than the
    raw image/device. Operating on such a path risks journal replay, atime
    updates, and mount-count bumps (PITFALLS P1). The guard therefore refuses any
    source whose real (symlink-resolved) path **is a mountpoint** in
    ``/proc/mounts`` (other than the root ``/``).

    Ordinary evidence files that merely *reside on* a non-root partition (e.g. a
    raw image stored under ``/home`` or ``/tmp``) are permitted: only a path that
    is itself a mountpoint root is refused, which is the unambiguous "this is a
    mounted filesystem" signal and is portable across hosts where ``/tmp`` /
    ``/home`` are separate mounts.

    Args:
        path: The evidence source path to validate.
        mounts_text: Optional ``/proc/mounts``-formatted text to consult instead
            of the real file (injectable for testing). Defaults to the live
            ``/proc/mounts``.

    Raises:
        MountedSourceError: If the source path is itself a non-root mountpoint.
    """
    if mounts_text is None:
        mounts_text = _read_proc_mounts()

    real_source = os.path.realpath(os.fspath(path))
    for mountpoint in _mountpoints(mounts_text):
        if mountpoint == os.sep:
            continue  # the root fs contains everything; not a meaningful refusal
        if real_source == mountpoint:
            raise MountedSourceError(
                f"refusing to operate on a mounted source: {real_source!s} is a "
                f"mounted filesystem (mountpoint {mountpoint!s}). Unmount the "
                "evidence and provide the raw image/device, or use a forensic "
                "write-blocker."
            )
