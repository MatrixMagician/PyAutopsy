"""HTML report renderer (REPORT-03 / D-22 / D-25/D-27).

:func:`render_html` renders the deterministic body (from
:func:`pyautopsy.report.assemble.assemble_report_body`) to a self-contained,
offline ``report.html`` via Jinja2:

* **autoescape ON** (``select_autoescape(["html","j2"])``): every
  evidence-controlled string (filenames, paths, file-type and limitation text)
  is HTML-escaped, so a ``<script>``-bearing filename renders as inert text
  (threat T-03-06). The template never uses ``| safe`` / ``Markup()`` on evidence.
* **bounded timeline (D-27)**: the HTML shows the in-process slice
  ``body["timeline"][:cap]`` (default 2000) — render_html takes NO store handle
  (W-2). When the true total ``M = body["timeline_total"]`` exceeds the shown
  count, an honest "Showing N of M timeline events" disclosure renders; when
  ``N == M`` no disclosure shows (no false alarm).
* **zero run metadata (W-1)**: render_html accepts no volatile-metadata argument
  and the template embeds no generation timestamp / host / duration / run-id, so
  ``report.html`` is itself whole-file byte-deterministic across runs (D-25).

The output path is built only from ``case_dir`` + the fixed name ``report.html``
under the realpath-confined ``case_dir/reports/`` directory (the confinement
covers that resolved directory, not a re-resolved final file path — the fixed
constant filename makes filename traversal impossible; WR-04, threat T-03-07).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from pyautopsy.report.jsonreport import _confined_reports_dir

__all__ = ["render_html"]

_HTML_NAME = "report.html"
_TEMPLATE_NAME = "report.html.j2"


def _build_env() -> Environment:
    """Build the offline, autoescaped, deterministic Jinja2 environment.

    Verbatim setup from 03-RESEARCH.md:322-341: templates are located via
    :func:`importlib.resources.files` (works installed or from a source checkout,
    no ``__file__`` guessing), autoescape neutralizes evidence-controlled strings,
    and ``trim_blocks`` / ``lstrip_blocks`` / ``keep_trailing_newline`` make the
    rendered whitespace editor-independent and deterministic (D-25).
    """
    from importlib.resources import files

    template_dir = files("pyautopsy.report") / "templates"
    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def render_html(body: dict[str, Any], case_dir: Path, *, cap: int = 2000) -> str:
    """Render the report body to ``case_dir/reports/report.html``.

    The timeline is sliced IN-PROCESS from the body (``body["timeline"][:cap]``)
    — the body already holds the full D-26-ordered list, so slicing it is O(cap)
    and never re-reads the store or re-materializes a fresh full list (Pitfall 5 /
    W-2). The true total ``M`` comes from ``body["timeline_total"]`` so the
    "Showing N of M" disclosure states real numbers. No volatile run-metadata is
    accepted or rendered (W-1).

    Args:
        body: The deterministic report body (from ``assemble_report_body``).
        case_dir: Root directory of the case.
        cap: Maximum number of timeline rows to render in the HTML (default 2000).

    Returns:
        The rendered HTML string (also written to ``reports/report.html``).

    Raises:
        ValueError: If the resolved output path escapes the case directory.
        OSError: If the file cannot be written.
    """
    shown = body["timeline"][:cap]
    total = body["timeline_total"]

    env = _build_env()
    template = env.get_template(_TEMPLATE_NAME)
    html = template.render(
        body=body,
        timeline=shown,
        timeline_total=total,
        cap=cap,
    )

    reports_dir = _confined_reports_dir(case_dir)
    path = reports_dir / _HTML_NAME
    path.write_text(html, encoding="utf-8")
    return html
