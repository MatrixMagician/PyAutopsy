"""Structured JSON report writer (REPORT-04, D-25/D-26/D-27).

:func:`write_json` serializes the deterministic report body produced by
:func:`pyautopsy.report.assemble.assemble_report_body` to
``case_dir/reports/report.json`` using the proven project primitive
``json.dumps(body, sort_keys=True, ensure_ascii=False)`` (audit/log.py:104):

* ``sort_keys=True`` — key order independent of dict construction order, so two
  runs on the same fixture are byte-identical (D-25).
* ``ensure_ascii=False`` — non-ASCII filenames survive as real UTF-8, not as
  ``\\u`` escapes.
* a single LOCKED trailing-newline convention — **no trailing newline** — so the
  whole-file byte-equality test in 03-03 has a stable target.

The JSON carries the FULL, unabridged D-26-ordered timeline (D-27): the bounded
view is an HTML-only concern. The output path is built ONLY from ``case_dir`` +
the fixed name ``report.json`` (never from evidence content — Pitfall 4) and is
confined to ``case_dir/reports/`` with the audit-log ``_is_within`` realpath
check. The body carries no run metadata, so ``report.json`` is body-only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pyautopsy.audit.log import _is_within

__all__ = ["write_json"]

_REPORTS_SUBDIR = "reports"
_JSON_NAME = "report.json"


def _confined_reports_dir(case_dir: Path) -> Path:
    """Resolve ``case_dir/reports`` and assert it stays inside the case dir.

    Mirrors the Phase 1 audit-log confinement (audit/log.py:52-57, 122-124): the
    path is derived only from ``case_dir`` + a fixed subdir, then re-checked with
    the realpath ``_is_within`` guard so a symlinked/relative ``case_dir`` cannot
    redirect report output outside the case (threat T-03-07). Creates the dir.

    Scope of the guarantee (WR-04): confinement covers the resolved *directory*,
    not a re-resolved final file path. That is sufficient because every report
    file written under it uses a FIXED constant name (``report.json`` /
    ``report.html`` / ``run_metadata.json``) — never an evidence-derived name —
    so traversal via the filename is impossible. The realpath check runs against
    the resolved dir BEFORE ``mkdir``, so this does not close a TOCTOU window on
    the directory itself; it defends against a statically symlinked/relative
    ``case_dir``, which is the threat model (T-03-07).

    Raises:
        ValueError: If the resolved reports dir escapes the case directory.
    """
    case_root = Path(case_dir).resolve()
    reports_dir = (case_root / _REPORTS_SUBDIR).resolve()
    if not _is_within(reports_dir, case_root):
        raise ValueError(
            f"reports path {reports_dir} escapes case directory {case_root}"
        )
    reports_dir.mkdir(parents=True, exist_ok=True)
    return reports_dir


def write_json(body: dict[str, Any], case_dir: Path) -> Path:
    """Write the report body to ``case_dir/reports/report.json``.

    Args:
        body: The deterministic report body (from ``assemble_report_body``);
            carries the FULL timeline and no run metadata.
        case_dir: Root directory of the case.

    Returns:
        The path of the written ``report.json``.

    Raises:
        ValueError: If the resolved output path escapes the case directory.
        OSError: If the file cannot be written.
    """
    reports_dir = _confined_reports_dir(case_dir)
    path = reports_dir / _JSON_NAME
    # No trailing newline (locked convention) — the 03-03 byte-equality test
    # asserts the exact bytes; sort_keys + ensure_ascii give determinism.
    serialized = json.dumps(body, sort_keys=True, ensure_ascii=False)
    path.write_text(serialized, encoding="utf-8")
    return path
