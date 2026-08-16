"""Tides at Shoreham — CLASS B: free API, stable, needs a key.

ADMIRALTY UK Tidal API, Discovery tier (free): 607 UK stations, today plus six days,
~10,000 requests/month. We use one request per day, so roughly 30 a month.

  Shoreham        = station 0081   <- ours
  Brighton Marina = station 0082
  (Hove is not a port.)

⚠ Discovery returns high/low water EVENTS only — time and height — NOT a continuous
tide curve. A real curve needs the paid Foundation/Premium tier. If the firmware ever
wants to draw a curve, interpolate between consecutive extremes (a sinusoid, or the
sailor's rule of twelfths). That is ample for a wall panel and costs nothing.

Key comes from the ADMIRALTY_API_KEY environment variable, which in CI is a GitHub
Actions repository secret. Secrets are NOT exposed in public repos.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import requests

STATION_SHOREHAM = "0081"
BASE = "https://admiraltyapi.azure-api.net/uktidalapi/api/V1"
UK = ZoneInfo("Europe/London")

# How many days of events to pull. We only display today, but the extra days let us
# calibrate "big tides" vs "small tides" against the actual week (see _range_label).
WINDOW_DAYS = 7


class TideError(RuntimeError):
    """Raised so build_data.py can carry forward the previous value and flag staleness."""


def _fetch_events(station: str, key: str) -> list[dict]:
    url = f"{BASE}/Stations/{station}/TidalEvents"
    try:
        r = requests.get(
            url,
            headers={"Ocp-Apim-Subscription-Key": key},
            params={"duration": WINDOW_DAYS},
            timeout=30,
        )
    except requests.RequestException as e:
        raise TideError(f"network error talking to Admiralty: {e}") from e

    if r.status_code == 401:
        raise TideError("Admiralty rejected the key (401) — check ADMIRALTY_API_KEY")
    if r.status_code == 429:
        raise TideError("Admiralty rate limit hit (429) — Discovery allows ~10k/month")
    if not r.ok:
        raise TideError(f"Admiralty returned {r.status_code}: {r.text[:200]}")

    events = r.json()
    if not isinstance(events, list) or not events:
        raise TideError("Admiralty returned no tidal events")
    return events


def _to_local(raw: str) -> datetime:
    """Admiralty timestamps are UTC. Convert once, here, so nothing downstream ever
    has to think about BST — least of all the Pico."""
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(UK)


def _day_range(events: list[dict]) -> float | None:
    """Height difference between the day's highest high and lowest low, in metres."""
    highs = [e["height_m"] for e in events if e["type"] == "HW"]
    lows = [e["height_m"] for e in events if e["type"] == "LW"]
    if not highs or not lows:
        return None
    return round(max(highs) - min(lows), 1)


def _range_label(today_range: float | None, all_ranges: list[float]) -> str:
    """Self-calibrating spring/neap label.

    Rather than hardcoding Shoreham's mean spring and neap ranges (which would be one
    more local fact to get wrong and maintain), compare today against the spread of the
    week the API just handed us. Over a 7-day window you nearly always straddle enough
    of the cycle for this to read correctly.
    """
    if today_range is None or len(all_ranges) < 3:
        return ""
    lo, hi = min(all_ranges), max(all_ranges)
    if hi - lo < 0.5:            # flat week, no meaningful contrast to draw
        return ""
    position = (today_range - lo) / (hi - lo)
    if position > 0.75:
        return "Big tides"
    if position < 0.25:
        return "Small tides"
    return "Middling tides"


def build(today: date) -> dict:
    key = os.environ.get("ADMIRALTY_API_KEY", "").strip()
    if not key:
        raise TideError("ADMIRALTY_API_KEY is not set — see README Setup")

    raw = _fetch_events(STATION_SHOREHAM, key)

    by_day: dict[date, list[dict]] = {}
    for e in raw:
        stamp = e.get("DateTime")
        height = e.get("Height")
        kind = (e.get("EventType") or "").lower()
        if not stamp or height is None:
            continue
        local = _to_local(stamp)
        by_day.setdefault(local.date(), []).append(
            {
                "type": "HW" if "high" in kind else "LW",
                "time": local.strftime("%H:%M"),
                "height_m": round(float(height), 1),
            }
        )

    todays = sorted(by_day.get(today, []), key=lambda e: e["time"])
    if not todays:
        raise TideError(f"no tidal events returned for {today.isoformat()}")

    today_range = _day_range(todays)
    all_ranges = [r for r in (_day_range(v) for v in by_day.values()) if r is not None]

    return {
        "port": "Shoreham",
        "events": todays,
        "range_m": today_range,
        "range_label": _range_label(today_range, all_ranges),
        "ok": True,
    }
