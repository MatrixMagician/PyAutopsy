"""Tests for the UTC-everywhere timestamp helper (D-10, PITFALLS P4).

The whole forensic timeline rests on tz-aware UTC timestamps. These tests pin
the contract: every helper is tz-aware by construction and naive datetimes are
rejected loudly rather than silently localised to the analysis host's timezone.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from pyautopsy.util import timeutil


def test_utc_now_is_tz_aware_utc() -> None:
    now = timeutil.utc_now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)
    assert now.tzinfo == timezone.utc


def test_iso_utc_default_ends_with_explicit_offset() -> None:
    stamp = timeutil.iso_utc()
    assert stamp.endswith("+00:00")


def test_iso_utc_roundtrips_to_tz_aware() -> None:
    stamp = timeutil.iso_utc()
    parsed = datetime.fromisoformat(stamp)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)


def test_iso_utc_accepts_explicit_aware_datetime() -> None:
    dt = datetime(2020, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert timeutil.iso_utc(dt) == "2020-01-02T03:04:05+00:00"


def test_iso_utc_normalises_non_utc_offset_to_utc() -> None:
    plus_two = timezone(timedelta(hours=2))
    dt = datetime(2020, 1, 2, 5, 0, 0, tzinfo=plus_two)
    # 05:00+02:00 == 03:00+00:00
    assert timeutil.iso_utc(dt) == "2020-01-02T03:00:00+00:00"


def test_iso_utc_rejects_naive_datetime() -> None:
    naive = datetime(2020, 1, 2, 3, 4, 5)
    with pytest.raises(ValueError):
        timeutil.iso_utc(naive)


def test_from_epoch_utc_zero_is_unix_epoch_utc() -> None:
    dt = timeutil.from_epoch_utc(0)
    assert dt.tzinfo == timezone.utc
    assert dt == datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert dt.isoformat() == "1970-01-01T00:00:00+00:00"


def test_from_epoch_utc_is_tz_aware_for_arbitrary_ts() -> None:
    dt = timeutil.from_epoch_utc(1_600_000_000)
    assert dt.tzinfo == timezone.utc
    assert dt.utcoffset() == timedelta(0)
