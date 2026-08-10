"""Path confinement for evidence-controlled names (D-33, PITFALLS P6).

Recovered file content is written under the case directory using a name that
came *from the evidence* — a deleted directory entry. That name is adversarial
input: it may be absolute, contain ``..`` components or a backslash separator,
or carry control characters that make a path unreadable in a report. Two
helpers make such a name safe to write with:

* :func:`sanitize_name` produces the on-disk write-name. The original name is
  always preserved separately as evidence; this is only what gets written.
* :func:`confined_target` resolves a name under a destination directory and
  proves, via ``realpath``, that the result stays inside it.

They are separate because they answer different questions. Sanitization decides
what a name should *look* like; confinement decides whether a resolved path is
*allowed*. Confinement is the security boundary and is never skipped, even for
an already-sanitized name — a symlinked destination can still redirect a name
that looks entirely benign.
"""

from __future__ import annotations

import os

__all__ = ["ConfinementRejected", "confined_target", "sanitize_name"]


class ConfinementRejected(Exception):
    """Raised when a name would write outside its destination directory.

    This is a refusal, not a warning: an evidence-controlled name that escapes
    the case directory is an attempt to write somewhere the examiner did not
    consent to.
    """


def sanitize_name(name: str) -> str:
    """Return a relative, control-char-free version of ``name``.

    Drops any drive/anchor, strips ``.`` and ``..`` components, and replaces
    path separators and control characters within a component. The result is
    only the safe on-disk write-name — callers keep the original name as
    evidence metadata.

    Args:
        name: The raw, evidence-controlled name.

    Returns:
        A relative POSIX-style path safe to join under a destination, or an
        empty string if nothing survives sanitization.
    """
    parts: list[str] = []
    for raw in name.replace("\\", "/").split("/"):
        if raw in ("", ".", ".."):
            continue
        cleaned = "".join(
            ch if (ch.isprintable() and ch not in "/:") else "_" for ch in raw
        )
        cleaned = cleaned.strip()
        if cleaned:
            parts.append(cleaned)
    return "/".join(parts)


def confined_target(dest_real: str, name: str) -> str:
    """Resolve ``name`` under ``dest_real`` and assert it stays inside it.

    Absolute names and ``..`` components are rejected *before* resolution, and
    the resolved realpath is then required to be the destination or live under
    it — which is what catches an escape through a symlink, where the name
    itself looks harmless.

    Args:
        dest_real: ``os.path.realpath`` of the destination directory.
        name: The name to confine, relative to ``dest_real``.

    Returns:
        The realpath of the write target, guaranteed inside the destination.

    Raises:
        ConfinementRejected: If the name is absolute, contains a ``..``
            component, or resolves outside the destination (path traversal).
    """
    if os.path.isabs(name) or name.startswith("/") or name.startswith("\\"):
        raise ConfinementRejected(f"absolute member path rejected: {name!r}")
    norm = name.replace("\\", "/")
    if any(part == ".." for part in norm.split("/")):
        raise ConfinementRejected(f"path-traversal component rejected: {name!r}")
    target = os.path.realpath(os.path.join(dest_real, norm))
    if target != dest_real and not target.startswith(dest_real + os.sep):
        raise ConfinementRejected(
            f"member escapes destination jail: {name!r} -> {target!r}"
        )
    return target
