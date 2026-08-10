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

* :mod:`registry` — the ``LogParser`` contract and the ``ParsedRecord`` it emits
  (EXT-01).
* :mod:`discover` — group + order rotated/gz log sets oldest→newest (D-45).
* :mod:`timeresolve` — D-46 tz/year inference with honest per-event flagging.
* :mod:`normalize` — parsed-record → :class:`TimelineEvent` transform (LOG-04).
* :mod:`auth` — the LOG-01 auth.log/secure parser + honest action/outcome taxonomy.
"""

from __future__ import annotations

from pyautopsy.log.auth import auth_parser
from pyautopsy.log.registry import LogParser, ParsedRecord
from pyautopsy.log.shell_history import shell_history_parser
from pyautopsy.log.syslog import syslog_parser
from pyautopsy.log.timeresolve import resolve_host_tz, to_utc, zone

__all__ = [
    "PARSERS",
    "LogParser",
    "ParsedRecord",
    "resolve_host_tz",
    "to_utc",
    "zone",
]

# The log parsers, in the order they are offered a file (EXT-01).
#
# This order is load-bearing, not cosmetic. It fixes which parser claims a
# basename when more than one could, and it fixes the per-line parse order,
# which — with discover's oldest→newest file order — fixes the
# ``insert_timeline_events`` order and therefore the store's surrogate-id
# tiebreak. That is the CR-01 deterministic-tied-order guarantee.
#
# It is stated here, in one readable line, instead of emerging from import
# order via a mutable registry. That indirection previously let the orchestrated
# path see only ``auth`` while the tests passed, because the tests imported the
# parser modules by hand and the CLI did not.
#
# To add a parser: implement the :class:`LogParser` contract and add it to this
# tuple. Nothing in :func:`pyautopsy.core.logs.run_logs` changes.
PARSERS: tuple[LogParser, ...] = (
    auth_parser,
    shell_history_parser,
    syslog_parser,
)
