"""The PyAutopsy command-line surface (Typer, D-12).

Phase 1 exposes a single ``ingest`` command plus ``--version``; the full
``analyze`` pipeline is assembled in Phase 3 on top of these primitives. The
Typer ``app`` defined in :mod:`pyautopsy.cli.main` is the ``[project.scripts]``
entry point declared in ``pyproject.toml``.
"""

from __future__ import annotations

from pyautopsy.cli.main import app

__all__ = ["app"]
