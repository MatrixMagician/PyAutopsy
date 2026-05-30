"""UTC-everywhere timestamp helper — the single sanctioned timestamp source.

Every timestamp PyAutopsy records (audit log, chain-of-custody, file MAC times)
must be timezone-aware UTC ISO-8601. This module is the *only* place the rest of
the code should obtain timestamps; later modules import from here instead of
calling :func:`datetime.now` or bare :func:`datetime.fromtimestamp` directly.

Rationale (D-10, PITFALLS P4): naive ``datetime`` values silently adopt the
analysis host's local timezone and lose their offset on serialization, which
poisons the forensic timeline and cannot be retrofitted. Establishing the
UTC-everywhere convention from the first phase prevents that class of bug.
"""

from __future__ import annotations

from datetime import datetime, timezone

__all__ = ["utc_now", "iso_utc", "from_epoch_utc"]


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC ``datetime``.

    Returns:
        A ``datetime`` whose ``tzinfo`` is :data:`datetime.timezone.utc`.
    """
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime | None = None) -> str:
    """Serialize a datetime to an ISO-8601 string with an explicit UTC offset.

    The result always carries an explicit ``+00:00`` offset; a bare local-time
    string is never produced. Aware datetimes in other zones are converted to
    UTC first.

    Args:
        dt: A timezone-aware datetime to serialize. Defaults to :func:`utc_now`.

    Returns:
        An ISO-8601 string ending in ``+00:00``.

    Raises:
        ValueError: If ``dt`` is naive (has no ``tzinfo``). Naive datetimes are
            rejected to prevent silent localisation to the analysis host's zone.
    """
    if dt is None:
        dt = utc_now()
    elif dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(
            "naive datetime rejected: timestamps must be timezone-aware UTC "
            "(use pyautopsy.util.timeutil helpers, never a bare datetime)"
        ) from None
    return dt.astimezone(timezone.utc).isoformat()


def from_epoch_utc(ts: int | float) -> datetime:
    """Convert a Unix epoch timestamp to a timezone-aware UTC ``datetime``.

    This is the sanctioned conversion for TSK / filesystem epoch times. It never
    uses a bare :func:`datetime.fromtimestamp` (which would apply the host's
    local timezone).

    Args:
        ts: Seconds since the Unix epoch (1970-01-01T00:00:00Z).

    Returns:
        The corresponding timezone-aware UTC ``datetime``.
    """
    return datetime.fromtimestamp(ts, tz=timezone.utc)
