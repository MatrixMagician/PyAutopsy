"""HTML report renderer (REPORT-03 / D-22) — placeholder for Task 2.

Task 1 lands the deterministic body + JSON writer; the package ``__init__``
re-exports :func:`render_html`, so a minimal definition exists here until Task 2
authors the autoescaped, bounded-timeline Jinja2 renderer + template.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = ["render_html"]


def render_html(body: dict[str, Any], case_dir: Path, *, cap: int = 2000) -> str:
    """Placeholder — implemented in Task 2."""
    raise NotImplementedError("render_html is implemented in Task 2")
