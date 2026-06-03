from copy import deepcopy
from datetime import datetime, timezone

from app.depletion import HIGH_TRAFFIC, LOW_TRAFFIC, MID_TRAFFIC
from app.json_state import DEFAULT_STATE, JsonStateStore, add_depletion_rate, prediction_from_json, prediction_to_json
from app.models import Prediction


def test_json_state_load_save(tmp_path) -> None:
    path = tmp_path / "state.json"
    store = JsonStateStore(path)

    state = store.load()
    assert state["last_quantity"] is None
    assert state["recent_restock_times"] == []
    assert state["depletion_rate_history"] == {
        LOW_TRAFFIC: [],
        MID_TRAFFIC: [],
        HIGH_TRAFFIC: [],
    }

    state["last_quantity"] = 5
    state["last_observed_at"] = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc).isoformat()
    store.save(state)

    loaded = JsonStateStore(path).load()
    assert loaded["last_quantity"] == 5
    assert loaded["last_observed_at"] == "2026-05-18T12:00:00+00:00"
    assert loaded["pending_notifications"] == []


def test_json_state_load_resets_legacy_flat_depletion_rate_history(tmp_path) -> None:
    path = tmp_path / "state.json"
    path.write_text(
        '{"depletion_rate_history": [250, 260], "depletion_rate_per_minute": 260, "current_cycle_depletion_rate_samples": [240]}',
        encoding="utf-8",
    )

    loaded = JsonStateStore(path).load()

    assert loaded["depletion_rate_history"] == {
        LOW_TRAFFIC: [],
        MID_TRAFFIC: [],
        HIGH_TRAFFIC: [],
    }
    assert loaded["depletion_rate_per_minute"] == 265
    assert loaded["current_cycle_depletion_rate_samples"] == [240.0]


def test_json_state_load_clears_legacy_sent_notification_keys(tmp_path) -> None:
    path = tmp_path / "state.json"
    path.write_text('{"sent_notification_keys": ["old-key"]}', encoding="utf-8")

    loaded = JsonStateStore(path).load()

    assert loaded["sent_notification_keys"] == []


def test_add_depletion_rate_uses_observed_at_bucket() -> None:
    state = deepcopy(DEFAULT_STATE)

    add_depletion_rate(
        state,
        300,
        max_items=20,
        observed_at=datetime(2026, 5, 19, 17, 0, tzinfo=timezone.utc),
    )

    assert state["depletion_rate_history"][HIGH_TRAFFIC] == [300.0]
    assert state["depletion_rate_history"][LOW_TRAFFIC] == []
    assert state["depletion_rate_history"][MID_TRAFFIC] == []


def test_add_depletion_rate_uses_explicit_bucket() -> None:
    state = deepcopy(DEFAULT_STATE)

    add_depletion_rate(state, 220, max_items=20, bucket=LOW_TRAFFIC)

    assert state["depletion_rate_history"][LOW_TRAFFIC] == [220.0]
    assert state["depletion_rate_history"][MID_TRAFFIC] == []
    assert state["depletion_rate_history"][HIGH_TRAFFIC] == []


def test_prediction_json_preserves_latest_departure_fields() -> None:
    prediction = Prediction(
        based_on_restock_event_id=1,
        predicted_restock_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        predicted_interval_ticks=25,
        prediction_method="DEFAULT_125_TICKS",
        airstrip_departure_at=datetime(2026, 1, 1, 10, 4, tzinfo=timezone.utc),
        business_departure_at=datetime(2026, 1, 1, 11, 7, tzinfo=timezone.utc),
        airstrip_latest_departure_at=datetime(2026, 1, 1, 10, 9, tzinfo=timezone.utc),
        business_latest_departure_at=datetime(2026, 1, 1, 11, 12, tzinfo=timezone.utc),
        airstrip_ping_at=datetime(2026, 1, 1, 10, 4, tzinfo=timezone.utc),
        business_ping_at=datetime(2026, 1, 1, 11, 7, tzinfo=timezone.utc),
        airstrip_target_restock_at=datetime(2026, 1, 1, 14, 5, tzinfo=timezone.utc),
        business_class_target_restock_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
    )

    decoded = prediction_from_json(prediction_to_json(prediction))

    assert decoded.airstrip_latest_departure_at == prediction.airstrip_latest_departure_at
    assert decoded.business_latest_departure_at == prediction.business_latest_departure_at
    assert decoded.airstrip_recommended_departure_at == prediction.airstrip_recommended_departure_at
    assert decoded.effective_airstrip_target_restock_at == prediction.effective_airstrip_target_restock_at
    assert decoded.effective_business_class_target_restock_at == prediction.effective_business_class_target_restock_at


def test_prediction_json_old_state_falls_back_to_recommended_as_latest() -> None:
    decoded = prediction_from_json(
        {
            "based_on_restock_event_id": 1,
            "predicted_restock_at": "2026-01-01T12:00:00+00:00",
            "predicted_interval_ticks": 25,
            "prediction_method": "DEFAULT_125_TICKS",
            "airstrip_departure_at": "2026-01-01T10:04:00+00:00",
            "business_departure_at": "2026-01-01T11:07:00+00:00",
            "airstrip_ping_at": "2026-01-01T10:04:00+00:00",
            "business_ping_at": "2026-01-01T11:07:00+00:00",
        }
    )

    assert decoded.airstrip_latest_departure_at == decoded.airstrip_departure_at
    assert decoded.business_latest_departure_at == decoded.business_departure_at
    assert decoded.effective_airstrip_target_restock_at == decoded.predicted_restock_at
    assert decoded.effective_business_class_target_restock_at == decoded.predicted_restock_at
