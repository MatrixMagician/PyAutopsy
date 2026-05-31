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

# Import the in-scope parser modules for their import-time self-registration side
# effect (EXT-01): each module's ``register(...)`` call runs on import, so simply
# importing the ``pyautopsy.log`` package (as ``core.logs`` does) guarantees the
# full declared-order registry — auth, syslog, shell-history — is populated on the
# orchestrated ``run_logs`` path, not just whichever parser a caller imported by
# hand. Without this, ``iter_parsers()`` returned only ``auth`` on the real CLI
# path while the Wave-2 tests passed because they imported the modules directly
# (CR-01). The ``noqa: F401`` marks the deliberate import-for-side-effect.
from pyautopsy.log import auth as _auth  # noqa: F401  (registers AuthParser)
from pyautopsy.log import (  # noqa: F401  (registers ShellHistoryParser)
    shell_history as _shell_history,
)
from pyautopsy.log import syslog as _syslog  # noqa: F401  (registers SyslogParser)
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
