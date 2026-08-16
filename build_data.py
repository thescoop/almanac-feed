#!/usr/bin/env python3
"""Build data.json — the single small payload the Pico fetches and draws.

DESIGN RULE: every ounce of complexity lives here, in Python. Timezones, BST, ISO
parsing, 12-to-24-hour conversion, string formatting. The Pico receives display-ready
strings and a handful of numbers, and never does date arithmetic. It has 520 KB of RAM
and no reason to know what a timezone is.

FAILURE ISOLATION: sources fail independently. If the pool scraper breaks, the tides,
the sun and the moon still publish, and the pool block carries forward its last good
value with ok=false plus the date it was last confirmed. A display trusted at a glance
must say when it has stopped knowing something, rather than showing stale data as fact.

Usage:
    python build_data.py            # writes data.json
    python build_data.py --dry-run  # prints it, writes nothing
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sources import pool, sun_moon, tides

OUT = Path(__file__).parent / "data.json"
UK = ZoneInfo("Europe/London")


def uk_date_label(d: date) -> str:
    """UK house style: "Sat 8 Aug '26". Built without %-d so it is portable."""
    return f"{d.strftime('%a')} {d.day} {d.strftime('%b')} '{d.strftime('%y')}"


def load_previous() -> dict:
    """Previous payload, for carrying forward whatever failed this run."""
    if not OUT.exists():
        return {}
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def run_source(name: str, fn, previous: dict, today: date) -> tuple[dict, str | None]:
    """Run one source. On failure carry the previous block forward, flagged stale.

    Returns (block, error_message_or_None) so the caller can report every failure at
    the end rather than dying on the first one.
    """
    try:
        block = fn(today)
        block["last_ok"] = today.isoformat()
        return block, None
    except Exception as e:                     # noqa: BLE001 — any failure is survivable
        stale = dict(previous.get(name) or {})
        stale["ok"] = False
        stale.setdefault("last_ok", None)
        return stale, f"{name}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the Almanac data payload.")
    ap.add_argument("--dry-run", action="store_true", help="print, do not write")
    args = ap.parse_args()

    today = datetime.now(UK).date()
    previous = load_previous()
    errors: list[str] = []

    # Class A first: computed, no network, cannot fail. If this ever throws, something
    # is wrong with the environment itself and the run SHOULD die.
    sun_block, moon_block = sun_moon.build(today)

    tide_block, err = run_source("tide", tides.build, previous, today)
    if err:
        errors.append(err)
    pool_block, err = run_source("pool", pool.build, previous, today)
    if err:
        errors.append(err)

    payload = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "date_label": uk_date_label(today),
        "sun": sun_block,
        "moon": moon_block,
        "tide": tide_block,
        "pool": pool_block,
        # One flag the firmware can check to decide whether to show a warning banner.
        "all_ok": not errors,
    }

    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    if args.dry_run:
        print(rendered)
    else:
        OUT.write_text(rendered, encoding="utf-8")
        print(f"wrote {OUT} ({len(rendered)} bytes)")

    for e in errors:
        print(f"WARNING  {e}", file=sys.stderr)

    # Exit 0 even when a source failed: the payload is still valid and worth publishing,
    # and a red X on every run would train us to ignore it. Genuine breakage shows up as
    # ok=false on the panel and in these warnings.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
