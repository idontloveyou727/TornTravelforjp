from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class StockObservation:
    observed_at: datetime
    item_id: int
    country: str
    quantity: int
    raw_payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class StockEvent:
    event_type: str
    item_id: int
    country: str
    observed_at: datetime
    normalized_at: datetime | None
    previous_quantity: int | None
    current_quantity: int
    source_delay_seconds: int | None = None


@dataclass(frozen=True)
class Prediction:
    based_on_restock_event_id: int
    predicted_restock_at: datetime
    predicted_interval_ticks: int
    prediction_method: str
    airstrip_departure_at: datetime
    business_departure_at: datetime
    airstrip_latest_departure_at: datetime
    business_latest_departure_at: datetime
    airstrip_ping_at: datetime
    business_ping_at: datetime
    airstrip_target_restock_at: datetime | None = None
    business_class_target_restock_at: datetime | None = None

    @property
    def airstrip_recommended_departure_at(self) -> datetime:
        return self.airstrip_departure_at

    @property
    def business_recommended_departure_at(self) -> datetime:
        return self.business_departure_at

    @property
    def effective_airstrip_target_restock_at(self) -> datetime:
        return self.airstrip_target_restock_at or self.predicted_restock_at

    @property
    def effective_business_class_target_restock_at(self) -> datetime:
        return self.business_class_target_restock_at or self.predicted_restock_at
