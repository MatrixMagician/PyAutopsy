"""Evidence tier — the single native seam and the integrity layer.

This package owns the *only* module that may import the native forensic
bindings (``pytsk3`` / ``pyewf``): :mod:`pyautopsy.evidence.image` (D-06,
ARCHITECTURE Anti-Pattern 1). Everything else in PyAutopsy consumes the plain
``read(offset, size)`` / ``get_size()`` interface that module exposes, so the
rest of the system is unit-testable without a real disk image and the native
dependency stays swappable.

:mod:`pyautopsy.evidence.integrity` is pure Python: it streams MD5 + SHA-256
over that read interface in a single pass, compares against a supplied
acquisition hash, re-verifies at end of run, and hard-guards against ever
mounting or writing the source (INGEST-02 / INGEST-03).
"""

from __future__ import annotations

from pyautopsy.evidence.image import (
    EWFImgInfo,
    ImageFormat,
    ImageHandle,
    ImageOpenError,
    open_image,
    tsk_version,
)
from pyautopsy.evidence.integrity import (
    IntegrityError,
    MountedSourceError,
    VerifyResult,
    assert_source_not_mounted,
    hash_image,
    reverify,
    verify_acquisition,
)

__all__ = [
    "EWFImgInfo",
    "ImageFormat",
    "ImageHandle",
    "ImageOpenError",
    "open_image",
    "tsk_version",
    "IntegrityError",
    "MountedSourceError",
    "VerifyResult",
    "assert_source_not_mounted",
    "hash_image",
    "reverify",
    "verify_acquisition",
]
