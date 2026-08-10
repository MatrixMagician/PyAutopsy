"""The LOG-03 shell-history (``.bash_history``/``.zsh_history``) parser + findings.

Per-user shell history is high-value DFIR evidence — but it is also the textbook
example of evidence that must NOT be presented as chronological truth (Pitfall 2,
D-44, Success Criterion 2):

* bare ``.bash_history`` lines carry **no per-line timestamp** at all; only when
  ``HISTTIMEFORMAT`` is set does bash interleave ``#<epoch>`` comment lines before
  each command. We use that epoch when present and otherwise emit the command with
  an explicit ``ts_basis="file-mtime-fallback; no per-line timestamp"`` flag (the
  enclosing orchestrator anchors the UTC instant to the file mtime, D-46) — we
  never invent a time.
* zsh *extended* history (``: <start>:<elapsed>;<command>``) embeds a start epoch
  we read directly into :attr:`ParsedRecord.epoch`.
* history is **trivially editable** by the very subject under investigation
  (``history -c`` clears it; lines can be reordered/forged), so file order is
  **not** chronological truth. The parser therefore surfaces an explicit
  *tamperability finding* (observed-fact only — "history is editable; order is not
  chronological truth"), never an asserted intent or guilt (the CON-03/RECOV-03
  honesty lineage).

The owning user is derived from the ``/home/<user>`` path when known and encoded
as ``actor="user=<name>"`` — never the literal ``"user=None"`` (WR-05); an unknown
owner yields ``actor=None``.

The parser is listed in the EXT-01 declared-order tuple
(:data:`pyautopsy.log.registry.PARSERS`) so
:func:`pyautopsy.core.logs.run_logs` selects it with NO orchestrator change.

Pure stdlib ``re`` on decoded text (Security V5 — DATA only): no native bindings
(D-14), no new runtime dependency (D-43).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from pyautopsy.log.registry import ParsedRecord

__all__ = [
    "ShellHistoryParser",
    "ShellHistoryResult",
    "parse",
    "shell_history_parser",
]

# zsh EXTENDED_HISTORY line: ": <start>:<elapsed>;<command>". The leading epoch is
# the command START time (the elapsed seconds are duration, not a second time).
_ZSH_EXTENDED = re.compile(r"^:\s*(?P<start>\d+):(?P<elapsed>\d+);(?P<cmd>.*)$")

# bash HISTTIMEFORMAT marker line: a standalone "#<epoch>" immediately preceding
# its command line. Whole-line match so a literal "#1700000000" comment in a
# command body is not misread as a timestamp.
_BASH_TS = re.compile(r"^#(?P<epoch>\d{9,11})\s*$")

# Owning user from a "/home/<user>/..." history path (the per-user actor signal).
_HOME_USER = re.compile(r"/home/(?P<user>[^/]+)/")

# The honest no-per-line-timestamp provenance flag (matches the orchestrator's
# fallback basis string so downstream flagging is uniform).
_NO_TS_BASIS = "file-mtime-fallback; no per-line timestamp"


@dataclass(frozen=True, slots=True)
class ShellHistoryResult:
    """The result of parsing one shell-history file: records + honesty findings.

    Unlike the line-oriented parsers, shell history is parsed into a small result
    object so the file-level *tamperability finding* (D-44) rides alongside the
    per-command records rather than being smuggled into a single record. The object
    is iterable over its records so it still flows through the registry/orchestrator
    that consumes a parser's output as an iterable of :class:`ParsedRecord`.

    Attributes:
        records: The parsed per-command records, in file order (determinism).
        findings: Honest, observed-fact-only findings about the source (here: a
            tamperability/no-chronology caveat) — never asserted intent.
    """

    records: list[ParsedRecord] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)

    def __iter__(self) -> Iterator[ParsedRecord]:
        """Iterate the records (so the result is usable as a parser's iterable)."""
        return iter(self.records)


def _actor_for(path: str | None) -> str | None:
    """Return ``"user=<name>"`` derived from a ``/home/<user>`` path, else ``None``."""
    if not path:
        return None
    m = _HOME_USER.search(path)
    return f"user={m.group('user')}" if m else None


def parse(
    text: str,
    ctx: dict[str, Any] | None = None,
    *,
    kind: str | None = None,
) -> ShellHistoryResult:
    """Parse decoded shell-history ``text`` into a :class:`ShellHistoryResult` (LOG-03).

    Detects the timestamp form per line (zsh extended ``: <start>:<elapsed>;cmd`` or
    bash ``#<epoch>`` marker preceding a command); a command with neither form is
    emitted with ``ts_basis`` set to the explicit no-per-line-timestamp flag rather
    than an invented time. Order is preserved (determinism) but is NOT treated as
    chronological truth — a tamperability finding (D-44) is always surfaced.

    Args:
        text: The decoded history text (one file).
        ctx: Optional orchestrator context; ``ctx["path"]`` (the history file path)
            seeds the per-user actor (``/home/<user>``).
        kind: ``"bash"`` or ``"zsh"`` hint. The line shapes are detected per line
            regardless, so the hint only annotates the records' ``attributes``.

    Returns:
        A :class:`ShellHistoryResult` carrying the per-command records and the
        file-level tamperability finding.
    """
    path = ctx.get("path") if ctx else None
    actor = _actor_for(path)
    records: list[ParsedRecord] = []
    pending_epoch: int | None = None  # a bash "#<epoch>" awaiting its command line

    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")
        if not line.strip():
            continue

        zsh = _ZSH_EXTENDED.match(line)
        if zsh is not None:
            cmd = zsh.group("cmd")
            records.append(
                ParsedRecord(
                    message=cmd,
                    actor=actor,
                    epoch=int(zsh.group("start")),
                    attributes={"raw": line, "kind": kind or "zsh"},
                )
            )
            pending_epoch = None
            continue

        bash_ts = _BASH_TS.match(line)
        if bash_ts is not None:
            # A bash HISTTIMEFORMAT marker: remember it for the NEXT command line.
            pending_epoch = int(bash_ts.group("epoch"))
            continue

        # A plain command line. If a bash "#<epoch>" preceded it, use that epoch;
        # otherwise there is NO per-line timestamp — flag the fallback, never fake.
        if pending_epoch is not None:
            records.append(
                ParsedRecord(
                    message=line,
                    actor=actor,
                    epoch=pending_epoch,
                    attributes={"raw": line, "kind": kind or "bash"},
                )
            )
            pending_epoch = None
        else:
            records.append(
                ParsedRecord(
                    message=line,
                    actor=actor,
                    ts_basis=_NO_TS_BASIS,
                    attributes={
                        "raw": line,
                        "kind": kind or "bash",
                        "ts_basis": _NO_TS_BASIS,
                    },
                )
            )

    findings = [
        "tamperability: shell history is editable by the subject (e.g. `history "
        "-c`) and its line order is NOT chronological truth — treat commands as "
        "observed evidence only, never as proof of timing or intent (D-44)."
    ]
    return ShellHistoryResult(records=records, findings=findings)


class ShellHistoryParser:
    """The LOG-03 :class:`~pyautopsy.log.registry.LogParser` for shell history."""

    name = "shell-history"

    def matches(self, path: str) -> bool:
        """Return ``True`` for ``.bash_history``/``.zsh_history`` history files."""
        leaf = path.rsplit("/", 1)[-1]
        return leaf in (".bash_history", ".zsh_history", ".history")

    @staticmethod
    def _kind_for(path: str) -> str:
        """Return the ``"zsh"``/``"bash"`` kind hint from a history path."""
        return "zsh" if path.endswith(".zsh_history") else "bash"

    def parse(
        self, text: str, ctx: dict[str, Any] | None = None
    ) -> Iterable[ParsedRecord]:
        """Parse decoded history text (delegates to :func:`parse`)."""
        path = (ctx or {}).get("path", "")
        return parse(text, ctx, kind=self._kind_for(path)).records

    def findings_for(
        self, text: str, ctx: dict[str, Any] | None = None
    ) -> list[str]:
        """Return this history file's honesty findings (D-44 tamperability).

        An additive concrete accessor that reaches the ``ShellHistoryResult.findings``
        the EXT-01 record-only :meth:`parse` contract intentionally drops, so
        :func:`pyautopsy.core.logs.run_logs` can surface the tamperability disclosure
        WITHOUT changing the shared ``LogParser.parse`` protocol signature. Reuses the
        same kind detection as :meth:`parse`.
        """
        path = (ctx or {}).get("path", "")
        return parse(text, ctx, kind=self._kind_for(path)).findings


# The module's parser singleton. Importing this module has no side effect:
# the parser takes effect only by being listed in ``registry.PARSERS`` (EXT-01).
shell_history_parser = ShellHistoryParser()
