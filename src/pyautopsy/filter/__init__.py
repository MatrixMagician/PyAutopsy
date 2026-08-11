"""Known-file filtering: NSRL membership + custom allow/block lists (FILTER-01).

This package is the noise-reduction layer. It answers one neutral question per
file — "is this hash *known* to a reference set?" — and never a good/bad/clean/
malicious verdict (D-38). Two membership sources are supported:

* :mod:`pyautopsy.filter.nsrl` — read-only membership probes against an
  examiner-supplied NSRL RDSv3 SQLite database (the ``FILE`` minimal variant or
  the ``METADATA`` modern variant, discovered at runtime), and
* :mod:`pyautopsy.filter.hashsets` — custom newline-delimited allow/block hash
  lists with hex-length algorithm inference.

Neither module imports the native forensic bindings (``pytsk3``/``pyewf``): all
filtering is stdlib ``sqlite3`` + text parsing, so this package stays OUTSIDE
the D-14 native-seam allowlist. The only ``sqlite3`` use here is the *read-only*
external NSRL DB — a distinct database from the case ``case.db`` (whose sole
writer remains :class:`pyautopsy.case.CaseStore`).
"""

from __future__ import annotations

from pyautopsy.filter.hashsets import (
    HashSet,
    parse_hash_set,
    probe_hash_set,
    to_known_match,
)
from pyautopsy.filter.nsrl import nsrl_match, open_nsrl

__all__ = [
    "HashSet",
    "nsrl_match",
    "open_nsrl",
    "parse_hash_set",
    "probe_hash_set",
    "to_known_match",
]
