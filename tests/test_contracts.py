"""Tests for the structural contracts (Protocols) the tiers depend on.

A protocol earns its place by having more than one implementation; otherwise it
is indirection that buys nothing, and a concrete type says more. These tests
pin the surviving protocols to the implementations that justify them, so a
future single-implementation protocol is a visible choice rather than a drift.
"""

from __future__ import annotations

from pathlib import Path

import pytsk3

from pyautopsy.evidence.byteio import ReadableBytes
from pyautopsy.evidence.image import EWFImgInfo, ImageHandle, open_image
from pyautopsy.log import PARSERS
from pyautopsy.log.registry import LogParser


def _satisfies_readable_bytes(obj: object) -> bool:
    """Structural check: does ``obj`` expose the ReadableBytes surface?"""
    return callable(getattr(obj, "read", None)) and callable(
        getattr(obj, "get_size", None)
    )


def test_readable_bytes_has_several_implementations(tiny_raw_image: Path) -> None:
    """The byte-source contract is shared by the native image, the handle, and fakes.

    More than one implementation is what justifies it being a protocol rather
    than a concrete type.
    """

    class InMemorySource:
        """The in-memory fake the integrity tests hash against (D-06)."""

        def read(self, offset: int, size: int) -> bytes:
            return b"\x00" * size

        def get_size(self) -> int:
            return 512

    handle = open_image(tiny_raw_image)
    try:
        implementations = [handle, handle.image, InMemorySource()]
        for impl in implementations:
            assert _satisfies_readable_bytes(impl), impl
        # The native binding and the adapter are genuinely distinct types.
        assert isinstance(handle, ImageHandle)
        assert isinstance(handle.image, pytsk3.Img_Info)
    finally:
        handle.close()


def test_readable_image_adds_exactly_close_over_readable_bytes() -> None:
    """``ReadableImage`` is the byte contract plus resource ownership.

    It inherits read/get_size rather than restating them; the only thing it adds
    is ``close``, because an opened image holds a native handle and a plain byte
    source does not.
    """
    from pyautopsy.evidence.image import ReadableImage  # noqa: PLC0415

    assert ReadableBytes in ReadableImage.__mro__
    own_methods = {
        name
        for name in vars(ReadableImage)
        if not name.startswith("_") and callable(vars(ReadableImage)[name])
    }
    assert own_methods == {"close"}


def test_ewf_adapter_and_raw_image_both_satisfy_the_image_contract() -> None:
    """Two real implementations back it: raw pytsk3 and the EWF adapter."""
    for impl in (pytsk3.Img_Info, EWFImgInfo):
        assert callable(getattr(impl, "read", None))
        assert callable(getattr(impl, "get_size", None))
        assert callable(getattr(impl, "close", None))
    # The adapter is a distinct type, not an alias of the native one.
    assert EWFImgInfo is not pytsk3.Img_Info
    assert issubclass(EWFImgInfo, pytsk3.Img_Info)


def test_log_parser_protocol_has_three_implementations() -> None:
    """``LogParser`` is a real extension seam: three parsers implement it."""
    assert len(PARSERS) == 3
    for parser in PARSERS:
        assert isinstance(parser, LogParser)
    assert len({type(p) for p in PARSERS}) == 3
