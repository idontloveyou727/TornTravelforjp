from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.db import decode_dt, encode_dt
from app.depletion import (
    DEFAULT_DEPLETION_RATE_PER_MINUTE,
    DEPLETION_RATE_BUCKETS,
    depletion_bucket_for_tct_time,
    empty_depletion_rate_history,
    normalize_depletion_rate_history,
)
from app.models import Prediction, StockObservation
from app.tick import diff_in_ticks

DEFAULT_PREDICTION_ACCURACY: dict[str, Any] = {
    "evaluated_count": 0,
    "correct_count": 0,
    "accuracy": None,
    "tolerance_ticks": None,
    "last_error_ticks": None,
}

DEFAULT_STATE: dict[str, Any] = {
    "last_quantity": None,
    "last_observed_at": None,
    "last_restock_normalized_at": None,
    "last_notified_restock_normalized_at": None,
    "last_estimated_depleted_at": None,
    "last_estimated_restock_at": None,
    "last_predicted_restock_at": None,
    "recent_restock_times": [],
    "recent_depleted_times": [],
    "depletion_rate_per_minute": None,
    "depletion_rate_history": empty_depletion_rate_history(),
    "current_cycle_depletion_rate_samples": [],
    "depletion_to_restock_interval_ticks": [],
    "active_prediction_evaluation": None,
    "prediction_evaluation_history": [],
    "prediction_accuracy": deepcopy(DEFAULT_PREDICTION_ACCURACY),
    "last_positive_observation": None,
    "pending_notifications": [],
    "sent_notification_keys": [],
}


class JsonStateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return deepcopy(DEFAULT_STATE)
        with self.path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        state = deepcopy(DEFAULT_STATE)
        if isinstance(loaded, dict):
            state.update(loaded)
        normalize_json_state(state)
        return state

    def save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
            handle.write("\n")
        tmp_path.replace(self.path)


def previous_observation_from_state(state: dict[str, Any], *, item_id: int, country: str) -> StockObservation | None:
    quantity = state.get("last_quantity")
    observed_at = state.get("last_observed_at")
    if quantity is None or observed_at is None:
        return None
    return StockObservation(
        observed_at=decode_dt(str(observed_at)),
        item_id=item_id,
        country=country,
        quantity=int(quantity),
    )


def update_last_observation(state: dict[str, Any], observation: StockObservation) -> None:
    state["last_quantity"] = observation.quantity
    state["last_observed_at"] = encode_dt(observation.observed_at)
    if observation.quantity > 0:
        state["last_positive_observation"] = observation_to_json(observation)


def observation_to_json(observation: StockObservation) -> dict[str, Any]:
    return {
        "observed_at": encode_dt(observation.observed_at),
        "item_id": observation.item_id,
        "country": observation.country,
        "quantity": observation.quantity,
    }


def observation_from_json(data: dict[str, Any] | None) -> StockObservation | None:
    if not data:
        return None
    return StockObservation(
        observed_at=decode_dt(str(data["observed_at"])),
        item_id=int(data["item_id"]),
        country=str(data["country"]),
        quantity=int(data["quantity"]),
    )


def add_recent_restock_time(state: dict[str, Any], normalized_at: datetime, *, max_items: int) -> None:
    normalized = encode_dt(normalized_at)
    values = [str(value) for value in state.get("recent_restock_times", [])]
    if not values or values[-1] != normalized:
        values.append(normalized)
    state["recent_restock_times"] = values[-max_items:]
    state["last_restock_normalized_at"] = normalized


def add_recent_depleted_time(state: dict[str, Any], depleted_at: datetime, *, max_items: int) -> None:
    encoded = encode_dt(depleted_at)
    values = [str(value) for value in state.get("recent_depleted_times", [])]
    if not values or values[-1] != encoded:
        values.append(encoded)
    state["recent_depleted_times"] = values[-max_items:]
    state["last_estimated_depleted_at"] = encoded


def add_depletion_rate(
    state: dict[str, Any],
    rate_per_minute: float,
    *,
    max_items: int,
    observed_at: datetime | None = None,
    bucket: str | None = None,
) -> None:
    if rate_per_minute <= 0:
        return
    target_bucket = _resolve_depletion_rate_bucket(observed_at=observed_at, bucket=bucket)
    add_depletion_rates_to_bucket(
        state,
        target_bucket,
        [rate_per_minute],
        max_items=max_items,
    )
    state["depletion_rate_per_minute"] = float(rate_per_minute)


def normalize_json_state(state: dict[str, Any], *, max_history_items: int | None = None) -> None:
    legacy_flat_history = not isinstance(state.get("depletion_rate_history"), dict)
    state["depletion_rate_history"] = normalize_depletion_rate_history(
        state.get("depletion_rate_history"),
        max_items=max_history_items,
    )
    if legacy_flat_history:
        state["depletion_rate_per_minute"] = DEFAULT_DEPLETION_RATE_PER_MINUTE
    state["current_cycle_depletion_rate_samples"] = _positive_float_values(
        state.get("current_cycle_depletion_rate_samples", [])
    )
    state["active_prediction_evaluation"] = _active_prediction_evaluation_value(
        state.get("active_prediction_evaluation")
    )
    state["prediction_evaluation_history"] = _prediction_evaluation_history_values(
        state.get("prediction_evaluation_history", [])
    )
    _update_prediction_accuracy(state, tolerance_ticks=None)
    state["sent_notification_keys"] = []


def depletion_rate_history_for_bucket(state: dict[str, Any], bucket: str) -> list[float]:
    history = normalize_depletion_rate_history(state.get("depletion_rate_history"))
    state["depletion_rate_history"] = history
    return list(history.get(bucket, []))


def add_pending_depletion_rate_sample(state: dict[str, Any], rate_per_minute: float, *, max_items: int) -> None:
    if rate_per_minute <= 0:
        return
    values = _positive_float_values(state.get("current_cycle_depletion_rate_samples", []))
    values.append(float(rate_per_minute))
    state["current_cycle_depletion_rate_samples"] = values[-max_items:]


def current_cycle_depletion_rate_samples(state: dict[str, Any]) -> list[float]:
    values = _positive_float_values(state.get("current_cycle_depletion_rate_samples", []))
    state["current_cycle_depletion_rate_samples"] = values
    return list(values)


def clear_current_cycle_depletion_rate_samples(state: dict[str, Any]) -> None:
    state["current_cycle_depletion_rate_samples"] = []


def add_depletion_rates_to_bucket(
    state: dict[str, Any],
    bucket: str,
    rates_per_minute: list[float],
    *,
    max_items: int,
) -> None:
    history = normalize_depletion_rate_history(state.get("depletion_rate_history"))
    values = list(history.get(bucket, []))
    values.extend(_positive_float_values(rates_per_minute))
    history[bucket] = values[-max_items:]
    state["depletion_rate_history"] = history


def _resolve_depletion_rate_bucket(*, observed_at: datetime | None, bucket: str | None) -> str:
    if bucket is not None:
        if bucket not in DEPLETION_RATE_BUCKETS:
            raise ValueError(f"Unknown depletion rate bucket: {bucket}")
        return bucket
    if observed_at is None:
        raise ValueError("add_depletion_rate requires observed_at or bucket")
    return depletion_bucket_for_tct_time(observed_at)


def _positive_float_values(values: Any) -> list[float]:
    if not isinstance(values, list):
        return []
    parsed_values: list[float] = []
    for value in values:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            parsed_values.append(parsed)
    return parsed_values


def add_depletion_to_restock_interval(state: dict[str, Any], ticks: int, *, max_items: int) -> None:
    if ticks <= 0:
        return
    values = [int(value) for value in state.get("depletion_to_restock_interval_ticks", []) if int(value) > 0]
    values.append(int(ticks))
    state["depletion_to_restock_interval_ticks"] = values[-max_items:]


def store_active_prediction_evaluation(
    state: dict[str, Any],
    prediction: Prediction,
    *,
    tolerance_ticks: int,
    created_at: datetime,
    anchor_at: datetime | None = None,
) -> None:
    predicted = prediction.predicted_restock_at
    window = timedelta(minutes=tolerance_ticks)
    state["active_prediction_evaluation"] = {
        "predicted_restock_at": encode_dt(predicted),
        "window_start_at": encode_dt(predicted - window),
        "window_end_at": encode_dt(predicted + window),
        "predicted_interval_ticks": prediction.predicted_interval_ticks,
        "prediction_method": prediction.prediction_method,
        "created_at": encode_dt(created_at),
        "anchor_at": encode_dt(anchor_at) if anchor_at else None,
    }
    _update_prediction_accuracy(state, tolerance_ticks=tolerance_ticks)


def evaluate_active_prediction(
    state: dict[str, Any],
    *,
    actual_restock_at: datetime,
    tolerance_ticks: int,
    evaluated_at: datetime,
    max_items: int,
) -> dict[str, Any] | None:
    active = _active_prediction_evaluation_value(state.get("active_prediction_evaluation"))
    if active is None:
        state["active_prediction_evaluation"] = None
        _update_prediction_accuracy(state, tolerance_ticks=tolerance_ticks)
        return None
    state["active_prediction_evaluation"] = active

    predicted = decode_dt(str(active["predicted_restock_at"]))
    error_ticks = diff_in_ticks(predicted, actual_restock_at)
    result = {
        "predicted_restock_at": active["predicted_restock_at"],
        "actual_restock_at": encode_dt(actual_restock_at),
        "window_start_at": active["window_start_at"],
        "window_end_at": active["window_end_at"],
        "predicted_interval_ticks": int(active["predicted_interval_ticks"]),
        "prediction_method": str(active["prediction_method"]),
        "created_at": active["created_at"],
        "anchor_at": active.get("anchor_at"),
        "evaluated_at": encode_dt(evaluated_at),
        "error_ticks": error_ticks,
        "correct": abs(error_ticks) <= tolerance_ticks,
        "tolerance_ticks": tolerance_ticks,
    }
    history = _prediction_evaluation_history_values(state.get("prediction_evaluation_history", []))
    history.append(result)
    state["prediction_evaluation_history"] = history[-max_items:]
    state["active_prediction_evaluation"] = None
    _update_prediction_accuracy(state, tolerance_ticks=tolerance_ticks)
    return result


def recent_restock_datetimes(state: dict[str, Any]) -> list[datetime]:
    values: list[datetime] = []
    for value in state.get("recent_restock_times", []):
        try:
            values.append(decode_dt(str(value)))
        except ValueError:
            continue
    return values


def _prediction_evaluation_history_values(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    normalized: list[dict[str, Any]] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        try:
            normalized.append(
                {
                    "predicted_restock_at": str(value["predicted_restock_at"]),
                    "actual_restock_at": str(value["actual_restock_at"]),
                    "window_start_at": str(value["window_start_at"]),
                    "window_end_at": str(value["window_end_at"]),
                    "predicted_interval_ticks": int(value["predicted_interval_ticks"]),
                    "prediction_method": str(value["prediction_method"]),
                    "created_at": str(value["created_at"]),
                    "anchor_at": str(value["anchor_at"]) if value.get("anchor_at") is not None else None,
                    "evaluated_at": str(value["evaluated_at"]),
                    "error_ticks": int(value["error_ticks"]),
                    "correct": bool(value["correct"]),
                    "tolerance_ticks": int(value["tolerance_ticks"]),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return normalized


def _active_prediction_evaluation_value(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    try:
        return {
            "predicted_restock_at": str(value["predicted_restock_at"]),
            "window_start_at": str(value["window_start_at"]),
            "window_end_at": str(value["window_end_at"]),
            "predicted_interval_ticks": int(value["predicted_interval_ticks"]),
            "prediction_method": str(value["prediction_method"]),
            "created_at": str(value["created_at"]),
            "anchor_at": str(value["anchor_at"]) if value.get("anchor_at") is not None else None,
        }
    except (KeyError, TypeError, ValueError):
        return None


def _update_prediction_accuracy(state: dict[str, Any], *, tolerance_ticks: int | None) -> None:
    history = _prediction_evaluation_history_values(state.get("prediction_evaluation_history", []))
    state["prediction_evaluation_history"] = history
    evaluated_count = len(history)
    correct_count = sum(1 for value in history if value["correct"])
    if tolerance_ticks is None and history:
        tolerance_ticks = int(history[-1]["tolerance_ticks"])
    state["prediction_accuracy"] = {
        "evaluated_count": evaluated_count,
        "correct_count": correct_count,
        "accuracy": (correct_count / evaluated_count) if evaluated_count else None,
        "tolerance_ticks": tolerance_ticks,
        "last_error_ticks": int(history[-1]["error_ticks"]) if history else None,
    }


def add_pending_notification_once(
    state: dict[str, Any],
    *,
    key: str,
    notification_type: str,
    target_time: datetime,
    prediction: Prediction,
) -> bool:
    if key in state.get("sent_notification_keys", []):
        return False
    for notification in state.get("pending_notifications", []):
        if notification.get("key") == key:
            return False

    state.setdefault("pending_notifications", []).append(
        {
            "key": key,
            "notification_type": notification_type,
            "target_time": encode_dt(target_time),
            "status": "PENDING",
            "prediction": prediction_to_json(prediction),
        }
    )
    return True


def mark_notification_sent(state: dict[str, Any], key: str) -> None:
    sent = state.setdefault("sent_notification_keys", [])
    if key not in sent:
        sent.append(key)


def discard_sent_notification_key(state: dict[str, Any], key: str) -> None:
    sent = state.get("sent_notification_keys", [])
    if not isinstance(sent, list):
        state["sent_notification_keys"] = []
        return
    state["sent_notification_keys"] = [value for value in sent if value != key]


def prediction_to_json(prediction: Prediction) -> dict[str, Any]:
    return {
        "based_on_restock_event_id": prediction.based_on_restock_event_id,
        "predicted_restock_at": encode_dt(prediction.predicted_restock_at),
        "predicted_interval_ticks": prediction.predicted_interval_ticks,
        "prediction_method": prediction.prediction_method,
        "airstrip_departure_at": encode_dt(prediction.airstrip_departure_at),
        "business_departure_at": encode_dt(prediction.business_departure_at),
        "airstrip_recommended_departure_at": encode_dt(prediction.airstrip_recommended_departure_at),
        "business_recommended_departure_at": encode_dt(prediction.business_recommended_departure_at),
        "airstrip_latest_departure_at": encode_dt(prediction.airstrip_latest_departure_at),
        "business_latest_departure_at": encode_dt(prediction.business_latest_departure_at),
        "airstrip_ping_at": encode_dt(prediction.airstrip_ping_at),
        "business_ping_at": encode_dt(prediction.business_ping_at),
        "airstrip_target_restock_at": encode_dt(prediction.effective_airstrip_target_restock_at),
        "business_class_target_restock_at": encode_dt(prediction.effective_business_class_target_restock_at),
    }


def prediction_from_json(data: dict[str, Any]) -> Prediction:
    return Prediction(
        based_on_restock_event_id=int(data["based_on_restock_event_id"]),
        predicted_restock_at=decode_dt(str(data["predicted_restock_at"])),
        predicted_interval_ticks=int(data["predicted_interval_ticks"]),
        prediction_method=str(data["prediction_method"]),
        airstrip_departure_at=decode_dt(str(data.get("airstrip_recommended_departure_at", data["airstrip_departure_at"]))),
        business_departure_at=decode_dt(str(data.get("business_recommended_departure_at", data["business_departure_at"]))),
        airstrip_latest_departure_at=decode_dt(
            str(data.get("airstrip_latest_departure_at", data["airstrip_departure_at"]))
        ),
        business_latest_departure_at=decode_dt(
            str(data.get("business_latest_departure_at", data["business_departure_at"]))
        ),
        airstrip_ping_at=decode_dt(str(data["airstrip_ping_at"])),
        business_ping_at=decode_dt(str(data["business_ping_at"])),
        airstrip_target_restock_at=decode_dt(str(data.get("airstrip_target_restock_at", data["predicted_restock_at"]))),
        business_class_target_restock_at=decode_dt(
            str(data.get("business_class_target_restock_at", data["predicted_restock_at"]))
        ),
    )


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
