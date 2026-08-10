"""The single native seam — read-only image open (INGEST-01, D-04/D-05/D-06).

This is the **only** module in PyAutopsy permitted to import the native forensic
bindings ``pytsk3`` and (lazily) ``pyewf`` (D-06, ARCHITECTURE Anti-Pattern 1).
It opens a disk image *read-only at the byte layer* — it never mounts the source
(D-05, PITFALLS P1) — and hands the rest of the system a plain
:class:`ImageHandle` exposing ``read(offset, size)`` / ``get_size()`` so every
downstream tier (hashing, case store, audit, CLI) is unit-testable without a real
image and the native dependency stays swappable.

Two formats are supported:

* **raw / dd** — opened directly with :class:`pytsk3.Img_Info`, which is
  read-only by construction and never mounts.
* **E01 / EWF** — opened through the canonical :class:`EWFImgInfo` adapter (a
  :class:`pytsk3.Img_Info` subclass backed by a ``pyewf.handle``), reproduced
  verbatim from the libewf wiki / hecfblog recipe (01-RESEARCH.md §Code
  Examples). ``pyewf`` is imported lazily inside the E01 branch and gated behind
  the optional ``pyautopsy[ewf]`` extra; a missing library yields an actionable
  install hint, not a raw stack trace (PITFALLS P5).

No code path here ever writes to, mounts, or truncates the source.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Protocol

import pytsk3

from pyautopsy.errors import PyAutopsyError
from pyautopsy.evidence.byteio import ReadableBytes

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pyewf

__all__ = [
    "EWFImgInfo",
    "ImageFormat",
    "ImageHandle",
    "ImageOpenError",
    "ReadableImage",
    "detect_format",
    "open_image",
    "tsk_version",
]

# Extensions that route to the EWF/E01 branch. Everything else is treated as a
# raw/dd byte image opened directly by pytsk3.
_EWF_SUFFIXES: frozenset[str] = frozenset({".e01", ".ex01", ".s01", ".l01"})


class ImageOpenError(PyAutopsyError):
    """Raised when an evidence image cannot be opened read-only.

    Carries an actionable, examiner-facing message (e.g. a missing file, or the
    ``pyautopsy[ewf]`` + ``libewf-dev`` install hint for the E01 path) rather
    than leaking a native ``ImportError`` / ``IOError`` stack trace.
    """


class ImageFormat(StrEnum):
    """Detected on-disk container format of an evidence image."""

    RAW = "raw"
    EWF = "ewf"


class ReadableImage(ReadableBytes, Protocol):
    """A :class:`ReadableBytes` source that also owns releasable resources.

    An opened image holds a native handle, so unlike a plain byte source it must
    be closed. That single extra method is the whole difference — the read/size
    half is inherited rather than restated.

    Both :class:`pytsk3.Img_Info` (raw) and :class:`EWFImgInfo` (E01) satisfy
    this, so downstream tiers depend on this structural contract — never on a
    concrete native type.
    """

    def close(self) -> None:
        """Release the underlying native resources."""


class EWFImgInfo(pytsk3.Img_Info):
    """A :class:`pytsk3.Img_Info` adapter over a ``pyewf.handle`` (E01/EWF).

    This is the canonical adapter recipe (01-RESEARCH.md §Code Examples): it
    constructs the base ``Img_Info`` with ``TSK_IMG_TYPE_EXTERNAL`` and delegates
    the byte-layer operations to the EWF handle. It performs **only** reads,
    seeks, size queries, and close — never a write — preserving the read-only
    evidence guarantee (INGEST-03).
    """

    def __init__(self, ewf_handle: pyewf.handle) -> None:
        """Wrap an opened ``pyewf.handle`` as a read-only ``Img_Info``.

        Args:
            ewf_handle: An already-opened ``pyewf.handle`` (opened read-only via
                ``pyewf.handle().open(...)``).
        """
        self._ewf_handle = ewf_handle
        super().__init__(url="", type=pytsk3.TSK_IMG_TYPE_EXTERNAL)

    def close(self) -> None:
        """Close the underlying EWF handle."""
        self._ewf_handle.close()

    def read(self, offset: int, size: int) -> bytes:
        """Read ``size`` bytes at ``offset`` from the EWF container.

        Args:
            offset: Byte offset from the start of the media.
            size: Number of bytes to read.

        Returns:
            The bytes read from the container.
        """
        self._ewf_handle.seek(offset)
        return self._ewf_handle.read(size)

    def get_size(self) -> int:
        """Return the media size reported by the EWF container."""
        return self._ewf_handle.get_media_size()


@dataclass(frozen=True, slots=True)
class ImageHandle:
    """A read-only, plain-Python handle over an opened evidence image.

    This value object carries the underlying native image (raw ``Img_Info`` or
    :class:`EWFImgInfo`) plus the total size and detected format, and exposes the
    structural :class:`ReadableImage` interface so the rest of the system never
    touches a ``pytsk3`` / ``pyewf`` type directly (D-06).

    Attributes:
        image: The underlying read-only native image (raw or EWF adapter).
        size: Total image size in bytes.
        image_format: The detected container format.
        path: The source path the image was opened from.
    """

    image: ReadableImage
    size: int
    image_format: ImageFormat
    path: Path

    def read(self, offset: int, size: int) -> bytes:
        """Read ``size`` bytes starting at ``offset`` (read-only)."""
        return self.image.read(offset, size)

    def get_size(self) -> int:
        """Return the total image size in bytes."""
        return self.size

    def close(self) -> None:
        """Release the underlying native image resources."""
        self.image.close()

    def __enter__(self) -> ImageHandle:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def detect_format(path: Path) -> ImageFormat:
    """Detect the evidence container format from a path's extension.

    ``.E01`` / ``.Ex01`` / ``.S01`` / ``.L01`` (case-insensitive) route to the
    EWF branch; everything else (``.dd``, ``.raw``, ``.img``, no extension, …) is
    treated as a raw/dd byte image.

    Args:
        path: The evidence image path.

    Returns:
        The detected :class:`ImageFormat`.
    """
    if path.suffix.lower() in _EWF_SUFFIXES:
        return ImageFormat.EWF
    return ImageFormat.RAW


def tsk_version() -> str:
    """Return the libtsk version string for the chain-of-custody record.

    Reads ``pytsk3.TSK_VERSION_STR``, the documented and stable name on the
    binding. This value is recorded in the evidence-source row and the audit
    trail, so it must be deterministic: a binding that grows a second
    version-ish attribute must not be able to change what gets recorded.

    Returns:
        A non-empty version string (e.g. ``"4.15.0"``), or ``"unknown"`` when
        the binding does not expose one.
    """
    value = getattr(pytsk3, "TSK_VERSION_STR", None)
    if isinstance(value, str) and value:
        return value
    return "unknown"


def _open_raw(path: Path) -> ImageHandle:
    """Open a raw/dd image read-only via :class:`pytsk3.Img_Info`."""
    try:
        img = pytsk3.Img_Info(os.fspath(path))
    except OSError as exc:
        raise ImageOpenError(
            f"could not open raw image {path!s}: {exc}"
        ) from exc
    return ImageHandle(
        image=img,
        size=img.get_size(),
        image_format=ImageFormat.RAW,
        path=path,
    )


def _open_ewf(path: Path) -> ImageHandle:
    """Open an E01/EWF image read-only via the :class:`EWFImgInfo` adapter.

    ``pyewf`` is imported lazily here so the core install works without libewf;
    a missing binding becomes an actionable install hint (PITFALLS P5).
    """
    try:
        import pyewf
    except ImportError as exc:
        raise ImageOpenError(
            f"cannot open E01/EWF image {path!s}: pyewf is not available. "
            "Install the EWF support extra with 'pip install pyautopsy[ewf]' "
            "and ensure the system libewf-dev / libewf package is present."
        ) from exc

    try:
        filenames = pyewf.glob(os.fspath(path))
        handle = pyewf.handle()
        handle.open(filenames)  # read-only
    except OSError as exc:
        raise ImageOpenError(
            f"could not open E01/EWF image {path!s}: {exc}"
        ) from exc

    img = EWFImgInfo(handle)
    return ImageHandle(
        image=img,
        size=img.get_size(),
        image_format=ImageFormat.EWF,
        path=path,
    )


def open_image(path: str | os.PathLike[str]) -> ImageHandle:
    """Open an evidence image read-only at the byte layer (INGEST-01).

    Routes by extension: raw/dd → :class:`pytsk3.Img_Info`; E01/EWF → the
    :class:`EWFImgInfo` adapter. The source is opened **read-only and is never
    mounted** (D-05, PITFALLS P1); no write/mount/losetup path exists here.

    Args:
        path: Path to the evidence image (a raw/dd file, or the first segment of
            an E01/EWF set).

    Returns:
        An :class:`ImageHandle` exposing ``read``/``get_size``/``close``.

    Raises:
        ImageOpenError: If the path does not exist or the image cannot be opened
            (including a missing ``pyewf`` for the E01 path, surfaced with an
            actionable install hint).
    """
    resolved = Path(path)
    if not resolved.exists():
        raise ImageOpenError(f"evidence image not found: {resolved!s}")

    if detect_format(resolved) is ImageFormat.EWF:
        return _open_ewf(resolved)
    return _open_raw(resolved)
