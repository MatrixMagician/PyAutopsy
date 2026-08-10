"""Tests for the single native seam — read-only image open (INGEST-01).

These prove the raw/dd open path against the committed ``tiny_raw.dd`` fixture
(pytsk3 is available on the host) and the format-detection routing that decides
between the pytsk3 (raw) and pyewf (E01) branches. The EWF adapter itself is
exercised in ``test_ewf_adapter.py`` against a mocked ``pyewf.handle`` because
the host lacks libewf (01-RESEARCH.md §Environment Availability / A4).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytsk3

from pyautopsy.evidence.image import (
    ImageFormat,
    ImageHandle,
    ImageOpenError,
    detect_format,
    open_image,
    tsk_version,
)


def test_open_raw_readonly(tiny_raw_image: Path) -> None:
    """``open_image`` opens the raw fixture read-only with a usable handle."""
    handle = open_image(tiny_raw_image)
    try:
        assert isinstance(handle, ImageHandle)
        assert handle.size > 0
        assert handle.get_size() == handle.size
        block = handle.read(0, 512)
        assert isinstance(block, bytes)
        assert len(block) == 512
    finally:
        handle.close()


def test_open_raw_reports_format(tiny_raw_image: Path) -> None:
    """A raw fixture is reported as the RAW format on the handle."""
    handle = open_image(tiny_raw_image)
    try:
        assert handle.image_format is ImageFormat.RAW
    finally:
        handle.close()


def test_handle_is_context_manager(tiny_raw_image: Path) -> None:
    """The handle supports ``with`` and reads correctly inside it."""
    with open_image(tiny_raw_image) as handle:
        assert handle.read(0, 16) == handle.read(0, 16)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("evidence.E01", ImageFormat.EWF),
        ("evidence.e01", ImageFormat.EWF),
        ("evidence.Ex01", ImageFormat.EWF),
        ("evidence.S01", ImageFormat.EWF),
        ("evidence.dd", ImageFormat.RAW),
        ("evidence.raw", ImageFormat.RAW),
        ("evidence.img", ImageFormat.RAW),
        ("disk", ImageFormat.RAW),
    ],
)
def test_format_detection_routes_by_extension(
    name: str, expected: ImageFormat
) -> None:
    """E01/Ex01/S01 route to EWF; raw/.dd/.raw/.img/no-ext route to RAW."""
    assert detect_format(Path(name)) is expected


def test_missing_file_raises_image_open_error(tmp_path: Path) -> None:
    """A non-existent path raises a clear ``ImageOpenError``, not a stack trace."""
    missing = tmp_path / "does-not-exist.dd"
    with pytest.raises(ImageOpenError):
        open_image(missing)


def test_e01_without_pyewf_raises_actionable_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Requesting an .E01 when pyewf is unavailable yields an install hint.

    The host lacks libewf, so importing ``pyewf`` fails. The seam must turn that
    into a specific, actionable ``ImageOpenError`` ("install pyautopsy[ewf]" +
    "libewf-dev") rather than leaking a raw ``ImportError`` stack trace
    (01-RESEARCH.md Pitfall 5).
    """
    e01 = tmp_path / "evidence.E01"
    e01.write_bytes(b"EVF\x09\x0d\x0a\xff\x00")  # arbitrary; never reached

    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "pyewf":
            raise ImportError("No module named 'pyewf'")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(ImageOpenError) as excinfo:
        open_image(e01)
    message = str(excinfo.value).lower()
    assert "ewf" in message
    assert "libewf" in message


def test_tsk_version_string_exposed() -> None:
    """A TSK version string is available for the chain-of-custody record."""
    version = tsk_version()
    assert isinstance(version, str)
    assert version  # non-empty


def test_tsk_version_reads_the_documented_attribute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The version comes from ``pytsk3.TSK_VERSION_STR``, not a name scan.

    The recorded tool version must be deterministic: it goes into the
    evidence-source row and the audit trail. Pinning it to the one documented
    attribute means a binding that grows another version-ish name cannot change
    what gets recorded.
    """
    monkeypatch.setattr(pytsk3, "TSK_VERSION_STR", "9.9.9-test", raising=False)
    # A decoy the old dir()-scan would have been free to pick up.
    monkeypatch.setattr(pytsk3, "OTHER_VERSION_STR", "0.0.0-decoy", raising=False)
    assert tsk_version() == "9.9.9-test"


def test_tsk_version_falls_back_to_unknown_when_attribute_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A binding without the attribute records ``"unknown"``, never a decoy."""
    monkeypatch.delattr(pytsk3, "TSK_VERSION_STR", raising=False)
    monkeypatch.setattr(pytsk3, "OTHER_VERSION_STR", "0.0.0-decoy", raising=False)
    assert tsk_version() == "unknown"
