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
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

__all__ = [
    "IntegrityError",
    "MountedSourceError",
    "VerifyResult",
    "assert_source_not_mounted",
    "hash_image",
    "reverify",
    "verify_acquisition",
]

# Default streaming chunk: 8 MiB — memory-bounded for multi-GB images while
# keeping read syscall overhead low (D-07, configurable).
_DEFAULT_CHUNK = 8 * 1024 * 1024

# Map a supplied hex-digest length to the algorithm it identifies.
_LEN_TO_ALGO: dict[int, str] = {32: "md5", 64: "sha256"}


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
    return {"md5": md5.hexdigest(), "sha256": sha256.hexdigest()}


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
            matches neither MD5 nor SHA-256), so it cannot be compared at all.
    """
    normalised = supplied.strip().lower()
    algorithm = _LEN_TO_ALGO.get(len(normalised))
    if algorithm is None or algorithm not in computed:
        raise IntegrityError(
            f"supplied acquisition hash is not a recognised md5/sha256 hex "
            f"digest (length {len(normalised)}): {supplied!r}"
        )
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


def _mountpoints(mounts_text: str) -> list[str]:
    """Parse mountpoint paths from ``/proc/mounts``-formatted text.

    Field 2 of each line is the mountpoint, with octal escapes for spaces etc.
    """
    points: list[str] = []
    for line in mounts_text.splitlines():
        fields = line.split()
        if len(fields) < 2:
            continue
        mountpoint = fields[1].encode("utf-8").decode("unicode_escape")
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
