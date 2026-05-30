"""Tests for the EWFImgInfo adapter (INGEST-01, E01 path) — mocked handle.

The host has no libewf, so the EWF adapter logic is unit-proven against a
``MagicMock`` standing in for a ``pyewf.handle`` (01-RESEARCH.md
§Environment Availability / A4). We assert the adapter delegates the byte-layer
operations to the underlying handle exactly as the canonical recipe requires:
``read(offset, size)`` → ``seek`` + ``read``; ``get_size()`` →
``get_media_size()``; ``close()`` → ``close()``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

# The adapter subclasses pytsk3.Img_Info, which the host has. If pytsk3 were
# absent this whole module would skip rather than hard-fail the suite.
pytsk3 = pytest.importorskip("pytsk3")

from pyautopsy.evidence.image import EWFImgInfo  # noqa: E402


def _make_handle(media_size: int = 4096, payload: bytes = b"\xab" * 32) -> MagicMock:
    handle = MagicMock(name="pyewf.handle")
    handle.get_media_size.return_value = media_size
    handle.read.return_value = payload
    return handle


def test_adapter_is_img_info_subclass() -> None:
    """EWFImgInfo is a pytsk3.Img_Info so pytsk3 can consume it transparently."""
    assert issubclass(EWFImgInfo, pytsk3.Img_Info)


def test_get_size_delegates_to_get_media_size() -> None:
    """``get_size()`` returns the handle's media size.

    Note: the pytsk3.Img_Info base ``__init__`` itself probes the size, so
    ``get_media_size`` is also invoked during construction; we assert the value
    and the delegation, not an exact call count.
    """
    handle = _make_handle(media_size=8192)
    img = EWFImgInfo(handle)
    handle.get_media_size.reset_mock()
    assert img.get_size() == 8192
    handle.get_media_size.assert_called_once_with()


def test_read_seeks_then_reads() -> None:
    """``read(offset, size)`` seeks to ``offset`` then reads ``size`` bytes."""
    payload = b"\x01\x02\x03\x04"
    handle = _make_handle(payload=payload)
    img = EWFImgInfo(handle)

    result = img.read(1024, 4)

    assert result == payload
    handle.seek.assert_called_once_with(1024)
    handle.read.assert_called_once_with(4)


def test_close_delegates_to_handle_close() -> None:
    """``close()`` closes the underlying pyewf handle."""
    handle = _make_handle()
    img = EWFImgInfo(handle)
    img.close()
    handle.close.assert_called_once_with()
