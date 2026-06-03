from __future__ import annotations

from app.models import StockEvent, StockObservation
from app.tick import floor_to_1_minute_tick

EVENT_INITIAL_STATE = "INITIAL_STATE"
EVENT_RESTOCK = "RESTOCK"
EVENT_OUT_OF_STOCK = "OUT_OF_STOCK"
EVENT_QUANTITY_CHANGE = "QUANTITY_CHANGE"


def detect_stock_event(previous: StockObservation | None, current: StockObservation) -> StockEvent | None:
    if previous is None:
        return StockEvent(
            event_type=EVENT_INITIAL_STATE,
            item_id=current.item_id,
            country=current.country,
            observed_at=current.observed_at,
            normalized_at=None,
            previous_quantity=None,
            current_quantity=current.quantity,
        )

    if previous.quantity == current.quantity:
        return None

    if previous.quantity == 0 and current.quantity > 0:
        normalized_at = floor_to_1_minute_tick(current.observed_at)
        return StockEvent(
            event_type=EVENT_RESTOCK,
            item_id=current.item_id,
            country=current.country,
            observed_at=current.observed_at,
            normalized_at=normalized_at,
            previous_quantity=previous.quantity,
            current_quantity=current.quantity,
            source_delay_seconds=int((current.observed_at - normalized_at).total_seconds()),
        )

    if previous.quantity > 0 and current.quantity == 0:
        return StockEvent(
            event_type=EVENT_OUT_OF_STOCK,
            item_id=current.item_id,
            country=current.country,
            observed_at=current.observed_at,
            normalized_at=None,
            previous_quantity=previous.quantity,
            current_quantity=current.quantity,
        )

    return StockEvent(
        event_type=EVENT_QUANTITY_CHANGE,
        item_id=current.item_id,
        country=current.country,
        observed_at=current.observed_at,
        normalized_at=None,
        previous_quantity=previous.quantity,
        current_quantity=current.quantity,
    )
