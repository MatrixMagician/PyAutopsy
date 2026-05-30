"""Evidence tier — the single native seam and the integrity layer.

This package owns the *only* module that may import the native forensic
bindings (``pytsk3`` / ``pyewf``): :mod:`pyautopsy.evidence.image` (D-06,
ARCHITECTURE Anti-Pattern 1). Everything else in PyAutopsy consumes the plain
``read(offset, size)`` / ``get_size()`` interface that module exposes, so the
rest of the system is unit-testable without a real disk image and the native
dependency stays swappable.
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

__all__ = [
    "EWFImgInfo",
    "ImageFormat",
    "ImageHandle",
    "ImageOpenError",
    "open_image",
    "tsk_version",
]
