"""Shared RFC3164 / RFC5424 syslog line grammar (stdlib ``re``).

``auth.log``/``secure`` and ``syslog``/``messages`` share the same on-disk line
shape, so the line grammar lives here once and is reused by the auth parser
(:mod:`pyautopsy.log.auth`) and the Wave-2 syslog parser. RFC3164 is the dominant
Linux format (``Mmm [d]d HH:MM:SS host program[pid]: msg`` — no year, no tz, which
is exactly why D-46 inference is required); RFC5424 is the modern ``<pri>1 …``
ISO-8601 variant some distros emit.

Pure stdlib ``re`` — no native bindings (D-14), no new runtime dependency (D-43).
Source grammar: rsyslog ``pmrfc3164`` docs + DFIR-standard practice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["SyslogLine", "RFC3164", "RFC5424", "parse_line"]

# RFC3164: "Mmm  d HH:MM:SS host program[pid]: msg" (day is space-padded to 2).
RFC3164 = re.compile(
    r"^(?P<ts>[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+"
    r"(?P<host>\S+)\s+"
    r"(?P<program>[^\s:\[]+)(?:\[(?P<pid>\d+)\])?:\s?"
    r"(?P<msg>.*)$"
)

# RFC5424: "<PRI>1 2026-05-31T12:00:00.000+00:00 host app pid msgid [sd] msg".
RFC5424 = re.compile(
    r"^<(?P<pri>\d+)>1\s+(?P<ts>\S+)\s+(?P<host>\S+)\s+(?P<app>\S+)\s+"
    r"(?P<pid>\S+)\s+(?P<msgid>\S+)\s+(?:-|\[.*?\])\s+(?P<msg>.*)$"
)


@dataclass(frozen=True, slots=True)
class SyslogLine:
    """One parsed syslog line's structural fields (format-agnostic).

    Attributes:
        program: The emitting program/service (``sshd``/``sudo``/``CRON``/...).
        host: The host field.
        pid: The process id text, or ``None``.
        message: The message body.
        raw_timestamp: The timestamp text as it appears (naive RFC3164 head, or
            the RFC5424 ISO-8601 string).
        is_rfc5424: ``True`` when the line was the modern RFC5424 form (its
            timestamp already carries a UTC offset and needs no D-46 inference).
    """

    program: str
    host: str
    pid: str | None
    message: str
    raw_timestamp: str
    is_rfc5424: bool


def parse_line(line: str) -> SyslogLine | None:
    """Parse one RFC3164/RFC5424 line into a :class:`SyslogLine`, or ``None``.

    Tries RFC5424 first (its leading ``<pri>1`` is unambiguous), then RFC3164.
    Returns ``None`` for a line matching neither (the caller still emits an
    unmatched record carrying the raw text — never silently drops it).
    """
    m5 = RFC5424.match(line)
    if m5 is not None:
        pid = m5.group("pid")
        return SyslogLine(
            program=m5.group("app"),
            host=m5.group("host"),
            pid=pid if pid not in ("-", "") else None,
            message=m5.group("msg"),
            raw_timestamp=m5.group("ts"),
            is_rfc5424=True,
        )
    m3 = RFC3164.match(line)
    if m3 is not None:
        return SyslogLine(
            program=m3.group("program"),
            host=m3.group("host"),
            pid=m3.group("pid"),
            message=m3.group("msg"),
            raw_timestamp=m3.group("ts"),
            is_rfc5424=False,
        )
    return None
