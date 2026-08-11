"""D-46 tz/year inference + honest per-event timestamp flagging.

RFC3164 log lines carry a month/day/time wall-clock with **no year and no
timezone** — the same "naive wall-clock → flagged UTC" problem the walk already
solved for FAT local time (:func:`pyautopsy.core.walk._macb_to_utc_iso`, D-16).
This module mirrors that exactly:

* :func:`resolve_host_tz` derives the image's local zone from ``/etc/localtime``
  (symlink target ``…/zoneinfo/<Zone>``) then ``/etc/timezone`` (Debian text),
  via reader callbacks supplied by the orchestrator (so this module stays
  pytsk3-free, D-14). On failure it returns ``(None, "tz-undeterminable")``.
* :func:`to_utc` interprets a naive wall-clock IN the host zone then converts to
  UTC through :func:`iso_utc` (which rejects naive datetimes — the structural
  SOUND-02 guard). The inference is ALWAYS flagged in the returned ``attributes``
  (``timestamp_source`` + ``assumed_timezone``); an undeterminable zone falls
  back to UTC **with an explicit warning flag**, never silently (the CR-01
  silent-offset lesson).
* :func:`infer_years` assigns each RFC3164 record a year, seeded from the log
  file mtime and decremented on a backwards month roll (logs are append-ordered,
  so a Dec→Jan jump within / across a rotated set crosses a year boundary). The
  inferred year + its basis are flagged per event.

This module imports no native bindings (D-14) and adds no runtime dependency
(D-43): pure ``datetime``/``zoneinfo`` + the project's :func:`iso_utc`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pyautopsy.util.timeutil import iso_utc

__all__ = [
    "zone",
    "resolve_host_tz",
    "to_utc",
    "rfc3164_components",
    "infer_years",
]

# Canonical provenance labels for the event ``timestamp_source`` attribute — the
# log-side sibling of ``walk._TIMESTAMP_SOURCE_BY_LABEL`` (D-16). These describe
# HOW a UTC instant was derived; they are asserted verbatim by the D-46 tests.
_TIMESTAMP_SOURCE_BY_LABEL: dict[str, str] = {
    "inferred-tz": "log:inferred-tz",
    "assumed-utc": "log:assumed-utc",
    "rfc5424": "log:rfc5424-offset",
}

# RFC3164 month abbreviations → 1..12 (the only month spelling in the format).
_MONTHS: dict[str, int] = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}


def zone(name: str) -> ZoneInfo:
    """Return a :class:`ZoneInfo` for an IANA zone ``name`` (validated here)."""
    return ZoneInfo(name)


def resolve_host_tz(
    *,
    read_symlink: Callable[[str], str | None],
    read_text: Callable[[str], str | None],
) -> tuple[ZoneInfo | None, str]:
    """Derive the image's local zone, or ``(None, "tz-undeterminable")``.

    Tries ``/etc/localtime``'s symlink target first (the canonical Linux source —
    a fast ext4 symlink whose target ``…/zoneinfo/<Zone>`` is only readable via
    the seam's symlink API, Assumption A5), then the ``/etc/timezone`` text
    fallback (Debian). Both are read through orchestrator-supplied callbacks so
    this module never imports pytsk3 (D-14).

    Args:
        read_symlink: ``path -> target | None`` symlink-target reader (seam).
        read_text: ``path -> text | None`` small-file text reader (seam).

    Returns:
        ``(ZoneInfo, "etc-localtime"|"etc-timezone")`` on success, else
        ``(None, "tz-undeterminable")`` — the caller then assumes UTC + warns.
    """
    target = read_symlink("/etc/localtime")
    if target:
        marker = "/zoneinfo/"
        idx = target.find(marker)
        zone_name = target[idx + len(marker) :] if idx >= 0 else target.lstrip("/")
        zone_name = zone_name.strip()
        if zone_name:
            try:
                return ZoneInfo(zone_name), "etc-localtime"
            except (ZoneInfoNotFoundError, ValueError):
                pass

    text = read_text("/etc/timezone")
    if text:
        zone_name = text.strip().splitlines()[0].strip() if text.strip() else ""
        if zone_name:
            try:
                return ZoneInfo(zone_name), "etc-timezone"
            except (ZoneInfoNotFoundError, ValueError):
                pass

    return None, "tz-undeterminable"


def to_utc(
    ts_naive_wallclock: datetime, host_tz: ZoneInfo | None
) -> tuple[str, dict[str, str]]:
    """Convert a naive wall-clock to a flagged UTC ISO-8601 string (D-46).

    Mirrors ``walk._macb_to_utc_iso`` (the FAT D-16 path): interpret the naive
    components IN ``host_tz`` then convert to UTC via :func:`iso_utc` (which
    raises on a naive datetime — naive is structurally impossible to persist).
    The inference is ALWAYS recorded in the returned attributes; an undeterminable
    zone falls back to UTC WITH an explicit warning (never silent — SOUND-02 /
    CR-01).

    Args:
        ts_naive_wallclock: The parsed naive wall-clock datetime (no tzinfo).
        host_tz: The inferred host zone, or ``None`` to assume UTC + warn.

    Returns:
        ``(utc_iso, attributes)`` where ``utc_iso`` ends in ``+00:00`` and
        ``attributes`` carries ``timestamp_source`` (+ ``assumed_timezone`` or a
        ``time_warning``).
    """
    if host_tz is None:
        dt = ts_naive_wallclock.replace(tzinfo=timezone.utc)
        return iso_utc(dt), {
            "timestamp_source": _TIMESTAMP_SOURCE_BY_LABEL["assumed-utc"],
            "time_warning": "WARNING: host timezone undeterminable; assumed UTC",
        }
    dt = ts_naive_wallclock.replace(tzinfo=host_tz)
    return iso_utc(dt), {
        "timestamp_source": _TIMESTAMP_SOURCE_BY_LABEL["inferred-tz"],
        "assumed_timezone": str(host_tz),
    }


def rfc3164_components(raw_timestamp: str) -> tuple[int, int, int, int, int] | None:
    """Parse an RFC3164 ``Mmm [d]d HH:MM:SS`` head into ``(mon, day, h, m, s)``.

    Returns ``None`` for an unparseable head (the record then carries no resolved
    time rather than aborting the parse). Tolerant of the space-padded day.
    """
    parts = raw_timestamp.split()
    if len(parts) < 3:
        return None
    mon = _MONTHS.get(parts[0])
    if mon is None:
        return None
    try:
        day = int(parts[1])
        hh, mm, ss = (int(x) for x in parts[2].split(":"))
    except (ValueError, IndexError):
        return None
    return mon, day, hh, mm, ss


def infer_years(
    components: list[tuple[int, int, int, int, int]],
    *,
    seed_year: int,
    seed_basis: str = "file mtime + rotation order",
) -> list[tuple[int, dict[str, object]]]:
    """Assign a year to each ordered RFC3164 record (D-46 year inference).

    Records are expected in append/rotation order (oldest→newest). The year is
    seeded from the log file's mtime on the NEWEST record and DECREMENTED only on a
    genuine calendar year boundary walking backwards in time. The boundary test
    compares the full ``(month, day)`` — NOT the month alone — so a same-month
    backward step (e.g. ``Jan 20`` → ``Jan 02``) is correctly recognised as the
    SAME year, and a real wrap (``Jan`` → ``Dec``) crosses to the previous year
    (CR-03: month-only comparison missed same-month boundaries).

    Robustness to a single out-of-order line (CR-03 cascade): the running anchor
    is the *minimum* ``(month, day)`` seen so far in the newer-side window, not the
    immediate predecessor. A lone late-dated line therefore does not become a new
    anchor that shifts every earlier record's year; the year only steps down when a
    record is genuinely later-in-the-calendar than everything newer than it AND the
    gap is a true December→January-class wrap (older month numerically greater AND
    the step spans the year-end, i.e. the older record sits in the back half of the
    year while the newer anchor sits in the front half). One anomalous line is thus
    absorbed instead of cascading a permanent year shift.

    Args:
        components: The ``(mon, day, h, m, s)`` heads in oldest→newest order.
        seed_year: The year to anchor the NEWEST record to (the evidence-derived
            seed; never a wall-clock year — CR-02).
        seed_basis: Provenance string recorded in each record's ``year_basis``.

    Returns:
        One ``(year, flags)`` per input record, in the same order; ``flags``
        carries ``year_inferred`` + ``year_basis``.
    """
    n = len(components)
    years: list[int] = [seed_year] * n
    if n == 0:
        return []

    # Walk newest→oldest. ``anchor_md`` is the EARLIEST-in-calendar (month, day)
    # seen among the records newer than the current position — using the running
    # minimum rather than the immediate successor stops one stray late-dated line
    # from re-anchoring (CR-03). A boundary is recognised only when it is a genuine
    # Dec→Jan-class wrap AND it is CONFIRMED by the next-older record (so a lone
    # out-of-order spike, whose older neighbour is back in the new-year range, is
    # absorbed instead of cascading a permanent shift).
    years[n - 1] = seed_year
    anchor_md = (components[n - 1][0], components[n - 1][1])
    for i in range(n - 2, -1, -1):
        cur_md = (components[i][0], components[i][1])
        wrap = (
            cur_md > anchor_md
            and components[i][0] >= 7  # older record in H2 (Jul–Dec)
            and anchor_md[0] <= 6  # anchor in H1 (Jan–Jun)
        )
        # Confirm the boundary is sustained so a lone out-of-order line does not
        # cascade a permanent year shift (CR-03). A wrap is confirmed when EITHER:
        #   (a) the NEXT-older record is also in the back half of the year (the
        #       original sustained-boundary signal), OR
        #   (b) the current record itself is a strong year-end signal — Nov/Dec
        #       (month >= 11) that is later-in-calendar than an H1 anchor. A
        #       Nov/Dec record preceding a Jan-side anchor is an unambiguous
        #       December->January wrap even when its own older neighbour happens to
        #       sit in H1 (WR-01 shape #1: a genuine boundary whose pre-boundary
        #       neighbour is early-year was previously refused, mis-dating it by a
        #       year). A lone mid-year spike (e.g. an August anomaly) still fails
        #       BOTH clauses, so the anti-cascade guarantee holds.
        confirmed = wrap and (
            i == 0 or components[i - 1][0] >= 7 or components[i][0] >= 11
        )
        years[i] = years[i + 1] - 1 if confirmed else years[i + 1]
        if confirmed:
            # New year segment: reset the anchor to this record's date.
            anchor_md = cur_md
        elif cur_md < anchor_md:
            # Still the same year; tighten the earliest-seen anchor.
            anchor_md = cur_md
    return [
        (
            years[i],
            {
                "year_inferred": years[i],
                "year_basis": seed_basis,
            },
        )
        for i in range(n)
    ]


def naive_from_components(year: int, comp: tuple[int, int, int, int, int]) -> datetime:
    """Build a naive :class:`datetime` from an inferred year + RFC3164 head."""
    mon, day, hh, mm, ss = comp
    return datetime(year, mon, day, hh, mm, ss)  # noqa: DTZ001 (naive by design)
