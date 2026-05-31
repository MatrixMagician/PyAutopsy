"""Syslog/messages line grammar entry point (LOG-02 grammar; full parse = Wave 2).

This Wave-1 module exposes the shared RFC3164/RFC5424 line grammar
(:func:`parse_line`) that the auth parser and the super-timeline depend on. The
full LOG-02 service/kernel/cron/error taxonomy (:func:`parse`) is built in Wave 2
and intentionally not implemented here — Wave 1 only stands up the reusable
grammar + the auth vertical slice.

Pure stdlib (no native bindings, D-14; no new runtime dependency, D-43).
"""

from __future__ import annotations

from pyautopsy.log._grammar import SyslogLine, parse_line

__all__ = ["SyslogLine", "parse_line"]
