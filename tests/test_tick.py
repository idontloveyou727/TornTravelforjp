from datetime import datetime, timezone

from app.tick import add_ticks, floor_to_1_minute_tick


def dt(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 5, 18, hour, minute, second, tzinfo=timezone.utc)


def test_floor_to_1_minute_tick_examples() -> None:
    assert floor_to_1_minute_tick(dt(12, 7, 12)) == dt(12, 7)
    assert floor_to_1_minute_tick(dt(12, 9, 59)) == dt(12, 9)
    assert floor_to_1_minute_tick(dt(12, 10, 1)) == dt(12, 10)
    assert floor_to_1_minute_tick(dt(8, 5, 0)) == dt(8, 5)
    assert floor_to_1_minute_tick(dt(23, 59, 59)) == dt(23, 59)


def test_add_ticks() -> None:
    assert add_ticks(dt(8, 5), 125) == dt(10, 10)
