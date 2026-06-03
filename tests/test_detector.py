from datetime import datetime, timezone

from app.detector import (
    EVENT_INITIAL_STATE,
    EVENT_OUT_OF_STOCK,
    EVENT_QUANTITY_CHANGE,
    EVENT_RESTOCK,
    detect_stock_event,
)
from app.models import StockObservation


def obs(quantity: int) -> StockObservation:
    return StockObservation(
        observed_at=datetime(2026, 5, 18, 12, 7, 12, tzinfo=timezone.utc),
        item_id=206,
        country="UK",
        quantity=quantity,
    )


def test_initial_state_zero() -> None:
    event = detect_stock_event(None, obs(0))
    assert event is not None
    assert event.event_type == EVENT_INITIAL_STATE


def test_initial_state_nonzero() -> None:
    event = detect_stock_event(None, obs(5))
    assert event is not None
    assert event.event_type == EVENT_INITIAL_STATE


def test_restock() -> None:
    event = detect_stock_event(obs(0), obs(10))
    assert event is not None
    assert event.event_type == EVENT_RESTOCK
    assert event.normalized_at == datetime(2026, 5, 18, 12, 7, tzinfo=timezone.utc)
    assert event.source_delay_seconds == 12


def test_out_of_stock() -> None:
    event = detect_stock_event(obs(10), obs(0))
    assert event is not None
    assert event.event_type == EVENT_OUT_OF_STOCK


def test_quantity_decrease() -> None:
    event = detect_stock_event(obs(10), obs(8))
    assert event is not None
    assert event.event_type == EVENT_QUANTITY_CHANGE


def test_quantity_increase_not_from_zero() -> None:
    event = detect_stock_event(obs(8), obs(12))
    assert event is not None
    assert event.event_type == EVENT_QUANTITY_CHANGE


def test_unchanged_zero() -> None:
    assert detect_stock_event(obs(0), obs(0)) is None
