"""Content-signature file typing via libmagic / python-magic (META-05, D-19).

File type is determined from the file's *content* (its leading bytes), never
from its extension (D-19): an attacker can name a shared library ``notes.txt``,
so on untrusted evidence the extension is meaningless. We read the leading bytes
through the read-only TSK ``File`` object (never mounting — D-05/P1) and pass
them to :func:`magic.from_buffer`.

This module is deliberately **isolated** from the rest of the walk so the
orchestrator stays unit-testable with a fake head-reader: it is *not* a pytsk3
seam (it must never import ``pytsk3``); ``python-magic`` wraps the system
``libmagic`` and is permitted outside the D-14 native seam allowlist.

Binding-collision guard (PITFALLS Pitfall 1 — HIGH): two PyPI distributions both
install a top-level ``magic`` module. ``python-magic`` (D-19, the one we want)
exposes :func:`magic.from_buffer`; ``file-magic`` (the freedesktop binding) does
*not* — it offers ``magic.Magic`` / ``magic.detect_from_content`` instead. If the
wrong binding wins the import, ``from_buffer`` would ``AttributeError`` at
runtime deep inside the walk. We assert the binding at import time and raise an
actionable :class:`ImportError` (mirroring the ``pyewf`` install-hint guard in
``image.py``) rather than failing obscurely later.
"""

from __future__ import annotations

from collections.abc import Callable

import magic

if not hasattr(magic, "from_buffer"):
    raise ImportError(
        "the installed 'magic' module is file-magic, not python-magic; "
        "install python-magic==0.4.27 (the two collide on the 'magic' name)."
    )

# ``HeadReader`` stays exported: it is the parameter type of the public
# ``file_type``, so a caller needs to be able to name it. ``_HEAD_BYTES`` is an
# internal read-size tuning constant and is private.
__all__ = ["HeadReader", "file_type"]

# Number of leading content bytes sampled for the signature lookup. libmagic only
# needs the head of the file; reading more would waste evidence-read bandwidth.
_HEAD_BYTES = 4096

# libmagic's MIME label for a zero-length file. Returned for empties without
# touching the binding (an empty buffer would otherwise type as
# "application/x-empty" inconsistently across libmagic versions).
EMPTY_TYPE = "inode/x-empty"


# A read-only callable yielding the leading bytes of a file. Implemented by the
# FS seam as a thin closure over the TSK ``File.read_random`` call so ``magic``
# never sees a native object and this module stays testable with a plain
# ``lambda offset, size: b"..."``. Kept a plain ``Callable`` alias (not a
# Protocol) so a positional-only seam closure matches structurally.
HeadReader = Callable[[int, int], bytes]


def file_type(read_head: HeadReader, size: int) -> str | None:
    """Return the content-derived MIME type for a file (META-05, D-19).

    Args:
        read_head: A read-only callable ``(offset, size) -> bytes`` returning the
            requested leading bytes of the file's content (the FS seam wraps the
            TSK ``File.read_random`` here; tests pass a fake).
        size: The file's logical size in bytes. ``0`` short-circuits to the
            empty-file sentinel without reading.

    Returns:
        The libmagic MIME string (e.g. ``"text/plain"``), ``"inode/x-empty"`` for
        a zero-length file, or ``None`` if no content could be read.
    """
    if size == 0:
        return EMPTY_TYPE
    head = read_head(0, min(_HEAD_BYTES, size))
    if not head:
        return None
    return magic.from_buffer(head, mime=True)
