"""The Lagoon at King Alfred, Hove — CLASS C: scraped, and the one thing here that WILL break.

Freedom Leisure runs King Alfred and embeds a third-party "Active In Time" timetable
widget. Verified against the live page 2026-08-16:

  * the timetable is STATIC HTML — no JavaScript rendering required
  * it accepts a `selected_date=YYYY-MM-DD` parameter
  * "lagoon" is a facility, alongside "main pool (25m)" and "teaching pool (12.5m)"

PAGE STRUCTURE (this is the bit that matters):

    ...~60 lines of chrome: day tabs, and TWO dropdowns listing every facility and
    every session type. "lagoon" APPEARS TWICE IN THOSE DROPDOWNS...
    Time                        <- header triple, our anchor
    Session
    Facility
    8:00 am - 9:00 am           <- rows from here, in strict triples
    Lane Swimming (6 lanes)
    main pool (25m)
    11:00 am - 5:00 pm
    Slide / Flume Available
    lagoon
    ...
    Powered by                  <- footer

⚠ THE TRAP: a naive "find lines containing lagoon" finds THREE matches on a day with
only ONE lagoon session, because two of them are dropdown options. Anchor on the
header and walk triples instead. (Cost one debug pass on 2026-08-16 — an earlier
regex-across-the-whole-page version silently returned 1 of N rows and looked fine.)

⚠ NO BROWSER NEEDED, AND DO NOT ADD ONE. Unlike Amazon or Rightmove, nobody defends a
swimming pool timetable — plain `requests` works. If this ever starts returning a
challenge page, something has changed; investigate rather than reaching for Playwright.
"""

from __future__ import annotations

import re
from datetime import date, datetime

import requests
from bs4 import BeautifulSoup

WIDGET = "https://www.activeintime.com/et/7961"
FACILITY = "lagoon"

TIME_RANGE = re.compile(
    r"^(?P<from>\d{1,2}:\d{2}\s*[ap]m)\s*[-–]\s*(?P<to>\d{1,2}:\d{2}\s*[ap]m)$",
    re.IGNORECASE,
)

# Sessions that mean the water is not actually available.
CLOSED_LABELS = {"pool closed", "private hire", "school swimming"}


class PoolError(RuntimeError):
    """Raised so build_data.py can carry forward the last good times and flag staleness."""


def _to_24h(value: str) -> str:
    """'9:45 am' -> '09:45'. The Pico must never see a 12-hour clock."""
    return datetime.strptime(re.sub(r"\s+", " ", value).strip().upper(), "%I:%M %p").strftime("%H:%M")


def _visible_lines(html: str) -> list[str]:
    text = BeautifulSoup(html, "html.parser").get_text("\n")
    return [re.sub(r"\s+", " ", ln).strip() for ln in text.split("\n") if ln.strip()]


def _find_table_start(lines: list[str]) -> int:
    """Index of the first data line, just past the Time/Session/Facility header."""
    for i in range(len(lines) - 2):
        if (
            lines[i].lower() == "time"
            and lines[i + 1].lower() == "session"
            and lines[i + 2].lower() == "facility"
        ):
            return i + 3
    raise PoolError(
        "could not find the Time/Session/Facility header — the page shape has changed"
    )


def _parse_rows(lines: list[str], start: int) -> list[tuple[str, str, str]]:
    """Walk the remaining lines in triples, stopping at the first non-time line."""
    rows: list[tuple[str, str, str]] = []
    i = start
    while i + 2 < len(lines) + 1:
        if i >= len(lines) or not TIME_RANGE.match(lines[i]):
            break                      # footer ("Powered by") or end of table
        if i + 2 >= len(lines):
            raise PoolError("timetable ended mid-row — the page shape has changed")
        rows.append((lines[i], lines[i + 1], lines[i + 2]))
        i += 3
    return rows


def build(today: date) -> dict:
    try:
        r = requests.get(
            WIDGET,
            params={"selected_date": today.isoformat()},
            timeout=30,
            headers={"User-Agent": "almanac-feed (personal wall display; contact via GitHub)"},
        )
    except requests.RequestException as e:
        raise PoolError(f"network error fetching the timetable: {e}") from e

    if not r.ok:
        raise PoolError(f"timetable returned HTTP {r.status_code}")

    lines = _visible_lines(r.text)
    rows = _parse_rows(lines, _find_table_start(lines))

    # Zero rows for the WHOLE centre means the parse failed, not that the pool is shut.
    # Those must never look the same on a display the family plans a Saturday around.
    if not rows:
        raise PoolError("header found but no timetable rows parsed — page shape changed")

    sessions = []
    seen: set[tuple[str, str, str]] = set()
    for when, label, facility in rows:
        if FACILITY not in facility.lower():
            continue
        m = TIME_RANGE.match(when)
        key = (_to_24h(m.group("from")), _to_24h(m.group("to")), label)
        # Their data genuinely repeats some rows (seen on Thu 20 Aug 2026: the same
        # 18:00-20:00 flume session listed twice). Identical time+label for the same
        # facility is a duplicate display row, not two things to swim in.
        if key in seen:
            continue
        seen.add(key)
        sessions.append(
            {
                "from": key[0],
                "to": key[1],
                "label": label,
                "open": label.lower() not in CLOSED_LABELS,
            }
        )

    sessions.sort(key=lambda s: (s["from"], s["to"]))
    # An empty list here is legitimate — the Lagoon simply has nothing on today.
    return {
        "facility": "Lagoon",
        "sessions": sessions,
        "rows_seen": len(rows),      # sanity signal: if this drops to 0 the parse broke
        "ok": True,
    }
