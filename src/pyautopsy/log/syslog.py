"""The LOG-02 ``syslog``/``messages`` parser + honest service/kernel/cron taxonomy.

``syslog``/``messages`` share the exact on-disk line shape with ``auth.log``/
``secure`` (RFC3164, or the modern RFC5424 variant), so this parser reuses the
shared :func:`pyautopsy.log._grammar.parse_line` grammar — it does NOT redefine a
divergent regex. On top of the parsed head it adds a small, honest, *program-based*
classification that describes **the observed line only** (never inferred intent —
the CON-03/RECOV-03 honesty lineage carried over from :mod:`pyautopsy.log.auth`):

* ``program == "kernel"`` → ``action="kernel"`` (a kernel ring-buffer line),
* ``program`` in {``CRON``, ``cron``, ``crond``} → ``action="cron"`` (a scheduled job),
* an error-level word in the message (``error``/``fail``/``critical``/...) →
  ``outcome="error"`` annotation, and
* anything else → ``action="service"`` (a generic service line).

The load-bearing LOG-02 signal is the **program (service) extraction**; the
level/facility heuristic is a non-authoritative annotation. A line that matches
the syslog grammar but no classification still becomes a record carrying its raw
message; a line that matches no grammar at all is likewise emitted with the raw
text — nothing is silently dropped (the auth parser's discipline).

For RFC3164 lines the naive wall-clock head is carried verbatim as
``raw_timestamp`` and resolved later through :mod:`pyautopsy.log.timeresolve`
(D-46 tz/year inference, flagged per event); RFC5424 lines already carry a UTC
offset and are flagged ``rfc5424`` for the resolver.

The parser is listed in the EXT-01 declared-order tuple
(:data:`pyautopsy.log.registry.PARSERS`), after
:class:`~pyautopsy.log.auth.AuthParser`, so
:func:`pyautopsy.core.logs.run_logs` selects it with NO orchestrator change.

Pure stdlib ``re`` on decoded text (Security V5 — DATA only): no native bindings
(D-14), no new runtime dependency (D-43).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from typing import Any

from pyautopsy.log._grammar import SyslogLine, parse_line
from pyautopsy.log.registry import ParsedRecord

__all__ = ["SyslogLine", "SyslogParser", "parse", "parse_line", "syslog_parser"]

# Programs whose lines are scheduled-job (cron) events — honest, observed-program
# only. Matched case-sensitively against the extracted program token.
_CRON_PROGRAMS: frozenset[str] = frozenset({"CRON", "cron", "crond"})

# An error-LEVEL heuristic over the message body: a non-authoritative annotation
# (``outcome="error"``) that flags a line whose text *names* an error/failure. It
# describes the observed word, never an inferred cause or intent (D-44 lineage).
_ERROR_LEVEL = re.compile(
    r"\b(?:error|errors|failed|failure|fatal|critical|crit|panic|segfault|"
    r"oom-kill|out of memory)\b",
    re.IGNORECASE,
)


def _classify(program: str | None, message: str) -> tuple[str | None, str | None]:
    """Return ``(action, outcome)`` for a syslog line (observed-line only).

    The action comes from the *program* (the load-bearing LOG-02 signal):
    ``kernel`` → ``"kernel"``, a cron program → ``"cron"``, otherwise the generic
    ``"service"``. The outcome is the non-authoritative error-level annotation:
    ``"error"`` when the message names an error/failure word, else ``None``. A
    line with no recognised program yields ``action=None`` but still keeps any
    error-level annotation.
    """
    outcome = "error" if _ERROR_LEVEL.search(message) else None
    if program is None:
        return None, outcome
    if program == "kernel":
        return "kernel", outcome
    if program in _CRON_PROGRAMS:
        return "cron", outcome
    return "service", outcome


def parse(text: str, ctx: dict[str, Any] | None = None) -> Iterator[ParsedRecord]:
    """Parse decoded ``syslog``/``messages`` ``text`` into records (LOG-02).

    Iterates lines tolerantly (blank lines skipped; a malformed line is emitted as
    an unmatched record, never aborting the parse). For each line: parse the
    RFC3164/RFC5424 head (program/host/pid/ts/msg) via the shared grammar, then
    classify by program + error-level heuristic. The classification describes the
    observed line only — never inferred intent (CON-03/RECOV-03/D-44 lineage).

    Args:
        text: The decoded log text (one set member, already gz-inflated upstream).
        ctx: Optional orchestrator context (ignored by this parser).

    Yields:
        One :class:`ParsedRecord` per non-blank line, in file order (determinism).
    """
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")
        if not line.strip():
            continue
        parsed = parse_line(line)
        if parsed is None:
            # No recognisable syslog head: keep the raw line as an unmatched event.
            yield ParsedRecord(message=line, attributes={"raw": line})
            continue
        action, outcome = _classify(parsed.program, parsed.message)
        yield ParsedRecord(
            message=parsed.message,
            raw_timestamp=parsed.raw_timestamp,
            program=parsed.program,
            host=parsed.host,
            pid=parsed.pid,
            action=action,
            outcome=outcome,
            attributes={
                "raw": line,
                "rfc5424": parsed.is_rfc5424,
            },
        )


class SyslogParser:
    """The LOG-02 :class:`~pyautopsy.log.registry.LogParser` for syslog (EXT-01)."""

    name = "syslog"

    def matches(self, path: str) -> bool:
        """Return ``True`` for ``syslog``/``messages`` (incl. rotated/gz members)."""
        leaf = path.rsplit("/", 1)[-1]
        return leaf.startswith("syslog") or leaf.startswith("messages")

    def parse(
        self, text: str, ctx: dict[str, Any] | None = None
    ) -> Iterable[ParsedRecord]:
        """Parse decoded syslog/messages text (delegates to :func:`parse`)."""
        return parse(text, ctx)


# The module's parser singleton. Importing this module has no side effect:
# the parser takes effect only by being listed in ``registry.PARSERS`` (EXT-01).
syslog_parser = SyslogParser()
