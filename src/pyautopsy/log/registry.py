"""The ``LogParser`` protocol + declared-order parser registry (EXT-01).

A minimal extension seam: each log format is a :class:`LogParser` (``name`` +
``matches(path)`` + ``parse(text, ctx)``) that emits :class:`ParsedRecord` value
objects; :func:`register` adds one to a module-level list iterated in **declared
order** by :func:`iter_parsers`. The declared order is load-bearing: it fixes the
per-line parse order, which (combined with discover's oldest→newest file order)
fixes the ``insert_timeline_events`` order and therefore the store's surrogate-id
tiebreak — the CR-01 deterministic-tied-order guarantee (Pitfall 3). Future Wave-2
parsers (syslog, shell-history) register here without touching
:func:`pyautopsy.core.logs.run_logs`.

This module imports no native bindings (D-14) and adds no runtime dependency
(D-43): it is pure ``dataclasses``/``typing``.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "ParsedRecord",
    "LogParser",
    "register",
    "iter_parsers",
    "clear_registry",
]


@dataclass(frozen=True, slots=True)
class ParsedRecord:
    """One parsed log line, normalized but NOT yet time-resolved (LOG-01/02/03).

    A pure value object the parsers emit and :mod:`pyautopsy.log.normalize`
    consumes. The timestamp is carried as the *raw* naive wall-clock string
    (``raw_timestamp`` — e.g. ``"Jan 15 02:02:45"``) plus any embedded epoch
    (``epoch`` for zsh/bash history); the UTC resolution + flagging happens later
    in :mod:`pyautopsy.log.timeresolve` so this stays a pure, host-tz-free parse.

    ``action``/``outcome`` describe **the observed line** only — never inferred
    intent (CON-03/RECOV-03 honesty lineage). A line that matches no known
    taxonomy pattern still becomes a record (``action=None``) carrying its raw
    ``message`` — never silently dropped.

    Attributes:
        message: The raw log message body (decoded ``utf-8``/``errors="replace"``,
            DATA only). Always populated — the line is never dropped.
        raw_timestamp: The naive wall-clock timestamp text as it appears on the
            line (no year, no tz for RFC3164), or ``None`` when the line carries
            no parseable timestamp head.
        program: The emitting program/service name (``sshd``/``sudo``/``CRON``/
            ``systemd``/...), or ``None``.
        host: The log host field, or ``None``.
        pid: The emitting process id as text, or ``None``.
        action: The honest, observed-line action label (``ssh-login``/``sudo``/
            ``session``/...), or ``None`` for an unmatched line.
        outcome: The honest outcome label (``success``/``failure``/``opened``/
            ``closed``/``granted``/``denied``/...), or ``None``.
        actor: ``"user=<name>"`` when a user is known on the line, else ``None``
            (never the literal ``"user=None"`` — WR-05 honesty).
        epoch: An embedded Unix epoch (zsh extended / bash ``#<epoch>``) when the
            format carries one, else ``None``.
        ts_basis: A provenance flag for the timestamp basis (e.g.
            ``"file-mtime-fallback; no per-line timestamp"``), or ``None``.
        attributes: Extra per-record JSON-serialisable data merged into the
            event ``attributes`` downstream (e.g. ``{"raw": <line>}``).
    """

    message: str
    raw_timestamp: str | None = None
    program: str | None = None
    host: str | None = None
    pid: str | None = None
    action: str | None = None
    outcome: str | None = None
    actor: str | None = None
    epoch: int | None = None
    ts_basis: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class LogParser(Protocol):
    """The minimal contract every log-format parser implements (EXT-01).

    A parser is identified by ``name``, claims paths via ``matches(path)``, and
    turns decoded log text into an iterable of :class:`ParsedRecord`. ``ctx`` is
    a free-form mapping the orchestrator may pass (e.g. the source log path /
    rotation index) — parsers ignore keys they do not need, so adding context
    never breaks an existing parser.
    """

    @property
    def name(self) -> str:
        """A stable, short parser name (e.g. ``"auth"``)."""
        ...

    def matches(self, path: str) -> bool:
        """Return ``True`` when this parser should handle the file at ``path``."""
        ...

    def parse(
        self, text: str, ctx: dict[str, Any] | None = None
    ) -> Iterable[ParsedRecord]:
        """Parse decoded log ``text`` into :class:`ParsedRecord` value objects."""
        ...


# The module-level registry, iterated in DECLARED (append) order for
# determinism (Pitfall 3). Parsers register at import time via :func:`register`.
_REGISTRY: list[LogParser] = []


def register(parser: LogParser) -> LogParser:
    """Append ``parser`` to the registry (declared order), returning it.

    Idempotent on identity: registering the same parser instance twice is a
    no-op so a re-imported module does not duplicate its parser (which would
    double every event and break the CR-01 deterministic count).
    """
    if parser not in _REGISTRY:
        _REGISTRY.append(parser)
    return parser


def iter_parsers() -> Iterator[LogParser]:
    """Yield the registered parsers in declared (registration) order."""
    yield from _REGISTRY


def clear_registry() -> None:
    """Empty the registry (test hook only)."""
    _REGISTRY.clear()
