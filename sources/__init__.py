"""Data sources for the Almanac feed.

Each module exposes a `build(today)` that either returns its block of the payload or
raises. Never let one source's failure take down another — that isolation lives in
build_data.py, and it is the reason a broken pool timetable still leaves the tides,
the sun and the moon on the wall.
"""
