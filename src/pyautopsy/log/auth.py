"""The LOG-01 ``auth.log``/``secure`` parser + honest action/outcome taxonomy.

Parses Linux authentication logs (sshd / sudo / PAM) from RFC3164 or RFC5424
lines into :class:`~pyautopsy.log.registry.ParsedRecord` value objects, mapping
well-known message shapes to a small, literal action/outcome vocabulary that
describes **the observed log line** — never inferred intent or guilt
(CON-03/RECOV-03 honesty lineage). A line that matches the syslog grammar but no
taxonomy pattern still becomes a record (``action=None``) carrying its raw
message; a line that matches no grammar at all is likewise emitted with the raw
text — nothing is silently dropped.

The parser is listed in the EXT-01 declared-order tuple
(:data:`pyautopsy.log.registry.PARSERS`) so
:func:`pyautopsy.core.logs.run_logs` selects it without special-casing.

Pure stdlib ``re`` on decoded text (Security V5 — DATA only): no native bindings
(D-14), no new runtime dependency (D-43).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from typing import Any

from pyautopsy.log._grammar import parse_line
from pyautopsy.log.registry import ParsedRecord

__all__ = ["AuthParser", "AUTH_PATTERNS", "parse", "auth_parser"]

# (action, outcome) for well-known auth message shapes — honest, observed-line
# only (RESEARCH Pattern 4). Each pattern may capture a ``user`` group used to
# build the honest ``actor``. Order is significant: the FIRST match wins, so the
# more specific sudo-failure pattern precedes the generic sudo-COMMAND grant.
AUTH_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (
        re.compile(r"Accepted \w+ for (?:invalid user )?(?P<user>\S+) from"),
        "ssh-login",
        "success",
    ),
    (
        re.compile(r"Failed password for (?:invalid user )?(?P<user>\S+)"),
        "ssh-login",
        "failure",
    ),
    (re.compile(r"authentication failure"), "sudo", "denied"),
    (re.compile(r"session opened for user (?P<user>\S+)"), "session", "opened"),
    (re.compile(r"session closed for user (?P<user>\S+)"), "session", "closed"),
    (re.compile(r"(?P<user>\S+) : .*COMMAND=(?P<cmd>.*)"), "sudo", "granted"),
    (re.compile(r"\b(?:new user|useradd)\b"), "account", "created"),
]

# Capture a ``user=<name>`` token the PAM lines carry even when no taxonomy
# pattern names a user group (e.g. the sudo authentication-failure line).
_USER_TOKEN = re.compile(r"\buser=(?P<user>\S+)")


def _classify(message: str) -> tuple[str | None, str | None, str | None]:
    """Return ``(action, outcome, user)`` for a message, or ``(None, None, user?)``.

    Describes the observed line only. An unmatched message yields ``action=None``
    / ``outcome=None`` but may still recover a ``user=`` token for the actor.
    """
    for pattern, action, outcome in AUTH_PATTERNS:
        m = pattern.search(message)
        if m is not None:
            user = m.groupdict().get("user")
            if not user:
                tok = _USER_TOKEN.search(message)
                user = tok.group("user") if tok else None
            return action, outcome, user
    tok = _USER_TOKEN.search(message)
    return None, None, (tok.group("user") if tok else None)


def parse(text: str, ctx: dict[str, Any] | None = None) -> Iterator[ParsedRecord]:
    """Parse decoded auth-log ``text`` into :class:`ParsedRecord` objects (LOG-01).

    Iterates lines tolerantly (blank lines skipped; a malformed line is emitted as
    an unmatched record, never aborting the parse). For each line: parse the
    RFC3164/RFC5424 head (program/host/pid/ts/msg), then classify the message body
    against :data:`AUTH_PATTERNS`. The actor is ``"user=<name>"`` only when a user
    is known (never the literal ``"user=None"`` — WR-05).

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
        action, outcome, user = _classify(parsed.message)
        actor = f"user={user}" if user else None
        yield ParsedRecord(
            message=parsed.message,
            raw_timestamp=parsed.raw_timestamp,
            program=parsed.program,
            host=parsed.host,
            pid=parsed.pid,
            action=action,
            outcome=outcome,
            actor=actor,
            attributes={
                "raw": line,
                "rfc5424": parsed.is_rfc5424,
            },
        )


class AuthParser:
    """The LOG-01 :class:`~pyautopsy.log.registry.LogParser` for auth logs (EXT-01)."""

    name = "auth"

    def matches(self, path: str) -> bool:
        """Return ``True`` for ``auth.log``/``secure`` (incl. rotated/gz members)."""
        leaf = path.rsplit("/", 1)[-1]
        return leaf.startswith("auth.log") or leaf.startswith("secure")

    def parse(
        self, text: str, ctx: dict[str, Any] | None = None
    ) -> Iterable[ParsedRecord]:
        """Parse decoded auth-log text (delegates to :func:`parse`)."""
        return parse(text, ctx)


# The module's parser singleton. Importing this module has no side effect:
# the parser takes effect only by being listed in ``registry.PARSERS`` (EXT-01).
auth_parser = AuthParser()
