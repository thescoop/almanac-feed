# almanac-feed

The data half of **Almanac** — a wall almanac for Hove built on a Raspberry Pi Pico 2 W.
This repo scrapes and computes the day's information once a day on GitHub Actions and
publishes it as a single small `data.json`. The Pico fetches that file and draws it.

**Firmware lives elsewhere:** `picoDevBoard/Almanac/` (private repo). Its `_handoff.md` is
the project's state doc — read that first.

## Why this repo is public

Not for openness — for a security reason. The Pico must fetch `data.json` **with no
credentials**. Raw file URLs on a private repo require an auth token, which would mean
baking a GitHub token into firmware sitting on a shelf, readable by anyone who dumps the
flash. A public repo serves the file to anyone who asks, so there is no secret on the device.

There is nothing confidential here: tide times and swimming pool hours are public facts.

**The fetch URL for the firmware:**
```
https://raw.githubusercontent.com/thescoop/almanac-feed/main/data.json
```

## How it works

```
GitHub Actions (daily cron)              Pico 2 W
  ├─ astral        → sun + moon            │
  ├─ Admiralty API → tides (Shoreham)      │  HTTPS GET data.json (~1 KB)
  ├─ Active In Time → Lagoon times         │  → parse → draw with LVGL
  └─ commits data.json  ───────────────────┘  → cache to flash, survive outages
```

**All complexity lives here, in Python.** Timezones, BST, ISO parsing, tidal
interpolation, string formatting. The Pico receives display-ready strings and a handful of
numbers, and never does date arithmetic. A microcontroller with 520 KB of SRAM cannot parse
a web page and has no JS engine — that is why the split exists.

## Sources, and how fragile each one is

| Class | Source | Breaks? |
|---|---|---|
| **A — computed** | `astral` — sunrise, sunset, day length, moon phase | never (no network) |
| **B — free API** | Admiralty UK Tidal (Discovery tier) — Shoreham, PortID `0081` | rarely |
| **C — scraped** | Active In Time widget — King Alfred Lagoon timetable | **will**, eventually |

Each source is isolated: if one fails, the others still publish, the last good value for the
failed section is carried forward, and its `ok` flag goes false. A display you trust at a
glance must tell you when it has stopped knowing something.

### Tides
- Shoreham is **PortID `0081`** (Brighton Marina is `0082`; Hove is not a port).
- The free **Discovery** tier gives ~10,000 requests/month across 607 UK stations, today
  plus six days. One call a day uses 30 of them.
- ⚠ Discovery returns **high/low water events only, not a continuous curve** — a curve needs
  the paid Foundation/Premium tier. We reconstruct one by interpolating between consecutive
  extremes. Fine for a wall panel.

### Lagoon timetable
- Freedom Leisure embeds a third-party **Active In Time** widget: `activeintime.com/et/7961`
- Verified 2026-08-08: the timetable is **static HTML as plain text** — no JavaScript
  rendering needed. It accepts a `selected_date=YYYY-MM-DD` parameter, and **"lagoon" is a
  named facility** alongside "main pool" and "teaching pool".
- This is the one source that will break. Keep the parser defensive and fail loudly.

## Setup

You need one secret: an **Admiralty API key** (free).

1. Register at the [ADMIRALTY Developer Portal](https://developer.admiralty.co.uk/) and
   subscribe to **UK Tidal API — Discovery** (free tier).
2. Add the key as a repository secret named `ADMIRALTY_API_KEY`
   (*Settings → Secrets and variables → Actions → New repository secret*).
   Secrets are **not** exposed in public repos.

Local development:

```bash
conda create -n almanac python=3.12 -y && conda activate almanac
pip install -r requirements.txt
export ADMIRALTY_API_KEY=...
python build_data.py            # writes data.json
python build_data.py --dry-run  # prints, writes nothing
```

## Schedule and gotchas

The workflow runs daily at **05:17 UTC** and can also be triggered by hand
(*Actions → refresh → Run workflow*).

- **Cron is UTC.** BST is handled in Python, not in the cron line.
- **Scheduled workflows are best-effort** and can run 10–30 minutes late — worst on the
  hour, which is why the schedule uses an odd minute.
- **Scheduled workflows are disabled after ~60 days of repository inactivity.** GitHub
  emails first. Whether the bot's own commits reset that clock is worth confirming rather
  than assuming.
- **Failed runs email the repo owner** by default. That is the monitoring, for free.

## No LLM at runtime

Claude was used at *build* time to work out the page structure and write the parser. The
running system is deterministic Python. An LLM that misreads a timetable produces a
confident, plausible, wrong time and you arrive at the pool an hour early with the kids.
Code either works or visibly breaks — for information trusted at a glance, that matters more
than flexibility.
