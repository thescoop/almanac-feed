"""Sun and moon for Hove — CLASS A: computed, no network, no API key, cannot break.

This module never makes an HTTP request. Everything here is astronomy derived from a
date and a latitude/longitude, so it works offline, has no rate limit, and will still
be correct in ten years when every API in this repo has been retired.

Build the rest of the feed around the assumption that THIS always succeeds.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from astral import LocationInfo, moon
from astral.sun import sun

# Hove, Sussex. Precise enough — a few hundred metres changes sunrise by under a second.
HOVE = LocationInfo("Hove", "England", "Europe/London", 50.8300, -0.1700)

# Mean synodic month (new moon to new moon), days. Used for the illumination curve.
SYNODIC_MONTH = 29.530588

_PHASE_NAMES = [
    (1.0, "New moon"),
    (6.5, "Waxing crescent"),
    (8.0, "First quarter"),
    (13.5, "Waxing gibbous"),
    (15.5, "Full moon"),
    (21.0, "Waning gibbous"),
    (22.5, "Last quarter"),
    (28.0, "Waning crescent"),
]


def _hhmm(dt) -> str:
    """Local-time HH:MM. astral returns tz-aware datetimes when given a tzinfo."""
    return dt.strftime("%H:%M")


def _daylight_seconds(d: date) -> float:
    s = sun(HOVE.observer, date=d, tzinfo=HOVE.timezone)
    return (s["sunset"] - s["sunrise"]).total_seconds()


def _phase_name(phase: float) -> str:
    """astral's moon.phase() is 0..27.99 — 0 new, 7 first quarter, 14 full, 21 last."""
    for limit, name in _PHASE_NAMES:
        if phase < limit:
            return name
    return "New moon"


def _illumination_pct(phase: float) -> int:
    """Fraction of the disc lit, from the phase angle. 0 at new, 100 at full."""
    fraction = (1 - math.cos(2 * math.pi * phase / SYNODIC_MONTH)) / 2
    return round(fraction * 100)


def build(today: date) -> tuple[dict, dict]:
    """Return (sun_block, moon_block) for the given local date."""
    s = sun(HOVE.observer, date=today, tzinfo=HOVE.timezone)

    today_len = _daylight_seconds(today)
    delta = today_len - _daylight_seconds(today - timedelta(days=1))
    direction = "more" if delta >= 0 else "less"
    mins, secs = divmod(int(abs(delta)), 60)

    sun_block = {
        "rise": _hhmm(s["sunrise"]),
        "set": _hhmm(s["sunset"]),
        "daylight": f"{int(today_len // 3600)}h {int(today_len % 3600 // 60):02d}m",
        # The single most quietly delightful field on the whole panel.
        "change_label": f"{mins}m {secs}s {direction} than yesterday",
        "ok": True,
    }

    phase = moon.phase(today)
    moon_block = {
        "phase": _phase_name(phase),
        "illum_pct": _illumination_pct(phase),
        "ok": True,
    }

    # moonrise/moonset legitimately do not occur on some days — astral returns None or
    # raises. That is not an error, so do not let it fail the whole block.
    for key, fn in (("rise", moon.moonrise), ("set", moon.moonset)):
        try:
            when = fn(HOVE.observer, today, tzinfo=HOVE.timezone)
            moon_block[key] = _hhmm(when) if when else None
        except (ValueError, AttributeError):
            moon_block[key] = None

    return sun_block, moon_block
