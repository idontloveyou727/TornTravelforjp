from __future__ import annotations

from datetime import datetime, timedelta

TICK_MINUTES = 1
TICKS_PER_DAY = 1440


def floor_to_1_minute_tick(dt: datetime) -> datetime:
    return dt.replace(second=0, microsecond=0)


def ceil_to_1_minute_tick(dt: datetime) -> datetime:
    floored = floor_to_1_minute_tick(dt)
    if dt == floored:
        return floored
    return floored + timedelta(minutes=1)


def floor_to_minute_tick(dt: datetime) -> datetime:
    return floor_to_1_minute_tick(dt)


def ceil_to_minute_tick(dt: datetime) -> datetime:
    return ceil_to_1_minute_tick(dt)


def floor_to_tick(dt: datetime) -> datetime:
    minute = dt.minute - (dt.minute % TICK_MINUTES)
    return dt.replace(minute=minute, second=0, microsecond=0)


def datetime_to_tick_index(dt: datetime) -> int:
    return (dt.hour * 60 + dt.minute) // TICK_MINUTES


def add_ticks(dt: datetime, ticks: int) -> datetime:
    return floor_to_tick(dt) + timedelta(minutes=ticks * TICK_MINUTES)


def diff_in_ticks(start: datetime, end: datetime) -> int:
    minutes = int((end - start).total_seconds() // 60)
    return minutes // TICK_MINUTES


def is_aligned_to_1_minute_tick(dt: datetime) -> bool:
    return dt.minute % TICK_MINUTES == 0 and dt.second == 0 and dt.microsecond == 0


def is_aligned_to_minute_tick(dt: datetime) -> bool:
    return is_aligned_to_1_minute_tick(dt)
