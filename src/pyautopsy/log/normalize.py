"""Parsed-record → :class:`TimelineEvent` transform (LOG-04).

The log-side mirror of :func:`pyautopsy.timeline.builder.explode`: a pure
transform that maps one parsed-and-time-resolved log record onto the shared
:class:`~pyautopsy.case.TimelineEvent` model so log events sit in the SAME
``timeline_events`` table — and therefore the SAME D-26 total order — as
filesystem events (the TIME-02 super-timeline, no new ordering code, D-47).

Two honesty disciplines carry over from the filesystem producer:

* the ``ts_utc`` string is taken **verbatim** from :mod:`pyautopsy.log.timeresolve`
  — never re-derived here (the tz/year inference + flagging is already done), and
* the actor is built from ONLY known components — a record with no user yields
  ``actor=None``, never the literal ``"user=None"`` (WR-05).

Imports no native bindings (D-14); adds no runtime dependency (D-43).
"""

from __future__ import annotations

from typing import Any

from pyautopsy.case import TimelineEvent
from pyautopsy.log.registry import ParsedRecord

__all__ = ["to_event"]


def to_event(
    parsed: ParsedRecord,
    *,
    evidence_source_id: int,
    file_id: int | None,
    source: str,
    log_path: str,
    utc_iso: str,
    attrs: dict[str, Any] | None = None,
    volume_id: int = 0,
    volume_offset: int = 0,
) -> TimelineEvent:
    """Map one parsed log record to a :class:`TimelineEvent` (LOG-04, pure).

    Args:
        parsed: The parsed (and time-resolved) log record. Supplies
            ``action``/``outcome``/``actor``/``message``.
        evidence_source_id: Owning evidence-source id.
        file_id: FK to the source log file's ``files`` row, or ``None`` when the
            log was parsed standalone (no prior walk).
        source: The event source label (``"auth"``/``"syslog"``/``"shell-history"``).
        log_path: The source log file path (the event's evidence reference).
        utc_iso: The resolved UTC ISO-8601 timestamp — copied verbatim, never
            re-derived (the D-46 flagging already happened in timeresolve).
        attrs: Per-event attributes (timestamp_source, assumed_timezone/year,
            raw msg). The record's own ``message`` is preserved under ``raw`` if
            not already present.
        volume_id: The source log file's volume id (``0`` when unknown).
        volume_offset: The source log file's volume byte offset (``0`` when unknown).

    Returns:
        A populated :class:`TimelineEvent` with ``meta_addr=None`` (log events
        have no inode) and the reserved Phase-5 ``action``/``outcome``/``file_id``
        columns filled.
    """
    # Honest actor: only when a user/actor is actually known (WR-05). The parser
    # already encodes ``"user=<name>"`` or ``None`` — never coerce to a literal.
    # (``or None`` collapses an empty string to the honest absent value.)
    actor = parsed.actor or None

    event_attrs: dict[str, Any] = dict(attrs) if attrs else {}
    if parsed.message is not None and "raw" not in event_attrs:
        event_attrs["raw"] = parsed.message

    return TimelineEvent(
        evidence_source_id=evidence_source_id,
        ts_utc=utc_iso,  # verbatim from timeresolve (D-46) — never re-derived
        source=source,
        event_type=parsed.action or "log",
        volume_id=volume_id,
        volume_offset=volume_offset,
        path=log_path,
        meta_addr=None,  # log events have no inode (nullable, schema-allowed)
        actor=actor,
        action=parsed.action,  # reserved column, now populated (D-23/D-47)
        outcome=parsed.outcome,
        file_id=file_id,  # FK to the log FILE's files row, or None (Open Q3)
        attributes=event_attrs,
    )
