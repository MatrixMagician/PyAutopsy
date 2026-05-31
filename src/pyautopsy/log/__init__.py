"""The ``pyautopsy.log`` package — log parsing into the shared timeline (Phase 5).

This package turns on-disk Linux log text (``auth.log``/``secure``, ``syslog``/
``messages``, shell history) read through the existing FS seam into normalized
:class:`~pyautopsy.case.TimelineEvent` rows for the TIME-02 super-timeline. It is
pure stdlib (``re``/``gzip``/``datetime``/``zoneinfo``) on top of the seam's
``read_random`` byte-reader closure: **no module here imports pytsk3/pyewf** —
all native access stays behind :mod:`pyautopsy.evidence.filesystem` (D-14, the
``tests/test_seam_allowlist.py`` gate). Likewise it adds **no new runtime
dependency** (D-43, the ``tests/test_no_new_deps.py`` gate).

The reusable scaffolding is:

* :mod:`registry` — the ``LogParser`` protocol + the declared-order parser
  registry (EXT-01): future parsers register here without touching
  :func:`pyautopsy.core.logs.run_logs`.
* :mod:`discover` — group + order rotated/gz log sets oldest→newest (D-45).
* :mod:`timeresolve` — D-46 tz/year inference with honest per-event flagging.
* :mod:`normalize` — parsed-record → :class:`TimelineEvent` transform (LOG-04).
* :mod:`auth` — the LOG-01 auth.log/secure parser + honest action/outcome taxonomy.
"""

from __future__ import annotations

from pyautopsy.log.registry import LogParser, ParsedRecord, iter_parsers, register
from pyautopsy.log.timeresolve import resolve_host_tz, to_utc, zone

__all__ = [
    "LogParser",
    "ParsedRecord",
    "iter_parsers",
    "register",
    "resolve_host_tz",
    "to_utc",
    "zone",
]
