"""The read-only byte-source contract shared by the evidence tiers.

Both the byte layer (:mod:`pyautopsy.evidence.image`) and the integrity layer
(:mod:`pyautopsy.evidence.integrity`) consume "something you can read bytes out
of by offset and ask the size of". That is one contract, so it is written once
here rather than restated in each module.

This module is deliberately native-free and dependency-free so the integrity
layer can depend on it without pulling ``pytsk3`` in behind it (D-06/D-14).
"""

from __future__ import annotations

from typing import Protocol

__all__ = ["ReadableBytes"]


class ReadableBytes(Protocol):
    """A read-only byte source addressable by offset.

    Satisfied structurally by :class:`pytsk3.Img_Info` (raw), the
    :class:`~pyautopsy.evidence.image.EWFImgInfo` adapter (E01),
    :class:`~pyautopsy.evidence.image.ImageHandle`, and by an in-memory fake in
    the tests — so no tier has to depend on a concrete native type (D-06).
    """

    def read(self, offset: int, size: int) -> bytes:
        """Read ``size`` bytes starting at ``offset``."""

    def get_size(self) -> int:
        """Return the total size in bytes."""
