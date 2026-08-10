"""Tests for path confinement of evidence-controlled names (D-33, P6).

These cover the security boundary directly, at its own public API, rather than
through the recovery orchestrator that consumes it. The cases mirror the
adversarial shapes a deleted directory entry can actually take: an absolute
path, a ``..`` traversal, a Windows-style backslash separator, a name that
resolves out of the destination through a symlink, and names carrying control
characters or separators inside a single component.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pyautopsy.util.confine import (
    ConfinementRejected,
    confined_target,
    sanitize_name,
)

# --------------------------------------------------------------------------
# confined_target — the security boundary
# --------------------------------------------------------------------------


def test_benign_relative_name_resolves_under_the_destination(tmp_path: Path) -> None:
    """An ordinary name resolves to a path inside the destination."""
    dest_real = os.path.realpath(tmp_path)
    target = confined_target(dest_real, "12-notes.txt")
    assert target == os.path.join(dest_real, "12-notes.txt")
    assert target.startswith(dest_real + os.sep)


def test_nested_relative_name_is_allowed(tmp_path: Path) -> None:
    """Subdirectories inside the destination are fine — only escapes are not."""
    dest_real = os.path.realpath(tmp_path)
    target = confined_target(dest_real, "sub/dir/9-file.bin")
    assert target == os.path.join(dest_real, "sub", "dir", "9-file.bin")


def test_absolute_path_is_rejected(tmp_path: Path) -> None:
    """An absolute name never writes to the absolute location."""
    dest_real = os.path.realpath(tmp_path)
    with pytest.raises(ConfinementRejected, match="absolute"):
        confined_target(dest_real, "/etc/passwd")


def test_dotdot_traversal_is_rejected(tmp_path: Path) -> None:
    """A ``..`` component is refused before the path is ever resolved."""
    dest_real = os.path.realpath(tmp_path)
    with pytest.raises(ConfinementRejected, match="traversal"):
        confined_target(dest_real, "../escaped.txt")


def test_backslash_separator_traversal_is_rejected(tmp_path: Path) -> None:
    """A Windows-style separator cannot smuggle a ``..`` past the check."""
    dest_real = os.path.realpath(tmp_path)
    with pytest.raises(ConfinementRejected, match="traversal"):
        confined_target(dest_real, "..\\escaped.txt")


def test_symlinked_name_that_resolves_outside_is_rejected(tmp_path: Path) -> None:
    """A name with no ``..`` in it still cannot escape via a symlink.

    This is why confinement resolves with ``realpath`` instead of trusting the
    textual form: ``link/file`` looks entirely benign.
    """
    dest = tmp_path / "dest"
    outside = tmp_path / "outside"
    dest.mkdir()
    outside.mkdir()
    (dest / "link").symlink_to(outside, target_is_directory=True)

    dest_real = os.path.realpath(dest)
    with pytest.raises(ConfinementRejected, match="escapes"):
        confined_target(dest_real, "link/file.txt")


def test_sibling_directory_prefix_is_not_mistaken_for_containment(
    tmp_path: Path,
) -> None:
    """``/case-evil`` must not pass as being inside ``/case`` on a prefix match."""
    dest = tmp_path / "case"
    dest.mkdir()
    (tmp_path / "case-evil").mkdir()
    dest_real = os.path.realpath(dest)

    (dest / "link").symlink_to(tmp_path / "case-evil", target_is_directory=True)
    with pytest.raises(ConfinementRejected, match="escapes"):
        confined_target(dest_real, "link/file.txt")


# --------------------------------------------------------------------------
# sanitize_name — what the on-disk name looks like
# --------------------------------------------------------------------------


def test_sanitize_strips_traversal_and_anchor() -> None:
    """Anchors and ``..``/``.`` components do not survive sanitization."""
    assert sanitize_name("/etc/passwd") == "etc/passwd"
    assert sanitize_name("../../etc/passwd") == "etc/passwd"
    assert sanitize_name("./a/./b") == "a/b"


def test_sanitize_normalises_backslash_separators() -> None:
    """A backslash is treated as a separator, not as part of a component."""
    assert sanitize_name("dir\\sub\\file.txt") == "dir/sub/file.txt"


def test_sanitize_replaces_control_characters() -> None:
    """Control characters become ``_`` so a name cannot corrupt a report line."""
    assert sanitize_name("bad\nname.txt") == "bad_name.txt"
    assert sanitize_name("bell\x07.txt") == "bell_.txt"


def test_sanitize_returns_empty_when_nothing_survives() -> None:
    """A name made entirely of traversal yields nothing, and callers substitute."""
    assert sanitize_name("../..") == ""
    assert sanitize_name("/") == ""


def test_sanitized_name_is_always_confinable(tmp_path: Path) -> None:
    """Sanitization feeds confinement: its output is never rejected as a path.

    The two helpers are used together, so this pins the contract between them —
    anything ``sanitize_name`` emits is a name ``confined_target`` accepts.
    """
    dest_real = os.path.realpath(tmp_path)
    for hostile in (
        "/etc/passwd",
        "../../etc/passwd",
        "dir\\..\\..\\escaped",
        "weird\nname",
        "a/../../b",
    ):
        safe = sanitize_name(hostile) or "unnamed"
        target = confined_target(dest_real, safe)
        assert target.startswith(dest_real + os.sep)
