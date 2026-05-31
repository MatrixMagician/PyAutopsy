"""Executable D-14 native-seam allowlist gate (architecture guard).

D-06/D-14 confine *all* native forensic-binding imports (``pytsk3`` / ``pyewf``)
to an explicit, documented seam allowlist: ``evidence/image.py`` (the byte-layer
seam) and ``evidence/filesystem.py`` (the FS-layer seam, added in Plan 02-01).
Until Phase 2 this rule was enforced only by *convention* (a manual ``grep``);
this test makes it an executable gate so the boundary cannot silently erode.

The gate is forgiving in one direction and strict in the other: ``filesystem.py``
is *permitted* to import the bindings if/when it exists ("permitted-if-present"),
so this test stays green today (only ``image.py`` imports ``pytsk3``) and remains
green once Plan 02-01 adds ``filesystem.py``. What it forbids — and fails on — is
*any* file OUTSIDE the allowlist importing ``pytsk3``/``pyewf``.
"""

from __future__ import annotations

import re
from pathlib import Path

# src/pyautopsy/ package root (this file lives at tests/test_seam_allowlist.py).
_SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "pyautopsy"

# The D-14 allowlist, as paths relative to the package root.
_ALLOWLIST: frozenset[str] = frozenset(
    {
        "evidence/image.py",
        "evidence/filesystem.py",
    }
)

# Matches a top-level `import pytsk3`, `import pyewf`, `from pytsk3 ...`,
# `from pyewf ...` anywhere in a line (indented lazy imports count too — they are
# still native-binding imports and must live in the seam). `from __future__` and
# unrelated modules are not matched.
_NATIVE_IMPORT = re.compile(
    r"^\s*(?:import|from)\s+(?:pytsk3|pyewf)\b",
    re.MULTILINE,
)


def _files_importing_native_bindings() -> set[str]:
    """Return allowlist-relative paths of src files importing pytsk3/pyewf."""
    offenders: set[str] = set()
    for py in _SRC_ROOT.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        if _NATIVE_IMPORT.search(text):
            offenders.add(py.relative_to(_SRC_ROOT).as_posix())
    return offenders


def test_native_bindings_only_imported_inside_seam_allowlist() -> None:
    """No file outside the D-14 allowlist may import pytsk3/pyewf."""
    importers = _files_importing_native_bindings()
    outside = importers - _ALLOWLIST
    assert not outside, (
        "native forensic bindings (pytsk3/pyewf) imported outside the D-14 seam "
        f"allowlist {sorted(_ALLOWLIST)}: {sorted(outside)}. Move the native call "
        "behind evidence/image.py or evidence/filesystem.py."
    )


def test_image_seam_is_a_native_importer() -> None:
    """Sanity: the byte-layer seam itself is (still) an allowlisted importer.

    Guards against the regex silently matching nothing (e.g. a refactor that
    renamed the import) and thereby making the allowlist test vacuously pass.
    """
    importers = _files_importing_native_bindings()
    assert "evidence/image.py" in importers
