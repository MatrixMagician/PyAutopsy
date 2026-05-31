"""Reporter tier — turns persisted case rows into the MVP report set.

This package reads back from the case store (the first read-side consumer of the
Phase 2 ``files`` rows and the Phase 3 ``timeline_events`` rows) and produces the
two MVP deliverables:

* a **structured JSON report** (REPORT-04) carrying the FULL D-26-ordered
  timeline, and
* a **human-readable HTML report** (REPORT-03, D-22) carrying a bounded,
  in-process slice of that same timeline with an honest "Showing N of M"
  truncation disclosure.

Both are driven by a single deterministic body dict produced by
:func:`assemble_report_body` (Pattern 3 — one determinism single-source-of-truth):
no wall-clock is reachable from the body, so two runs on the same fixture yield
byte-identical ``report.json`` and ``report.html`` (CLI-02 / D-25). Volatile run
metadata is segregated into :func:`build_run_metadata` and written to a separate
``reports/run_metadata.json`` sidecar by the ``analyze`` orchestrator (03-03, W-1);
it is NEVER merged into the body and NEVER passed to :func:`render_html`.

All outputs are confined to ``case_dir/reports/`` (path confinement, like the
Phase 1 audit log).
"""

from __future__ import annotations

from pyautopsy.report.assemble import assemble_report_body, build_run_metadata
from pyautopsy.report.htmlreport import render_html
from pyautopsy.report.jsonreport import write_json

__all__ = [
    "assemble_report_body",
    "build_run_metadata",
    "write_json",
    "render_html",
]
