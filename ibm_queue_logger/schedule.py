"""Schedule gating for cron-driven poll ticks."""

from __future__ import annotations

import datetime


def should_run_now(runs_per_day: int) -> tuple[bool, int]:
    """
    Returns (should_run, tick_index).

    Divides the UTC day into runs_per_day equal intervals.
    Tick fires if the current minute falls within the first minute of its interval.
    """
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    minutes_since_midnight = now.hour * 60 + now.minute
    interval_minutes = 1440 / runs_per_day
    tick_index = int(minutes_since_midnight / interval_minutes)
    tick_start_minute = round(tick_index * interval_minutes)
    return minutes_since_midnight == tick_start_minute, tick_index
