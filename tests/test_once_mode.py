from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path

import monitor
from app.config import Config
from app.depletion import HIGH_TRAFFIC, LOW_TRAFFIC, MID_TRAFFIC
from app.discord_webhook import discord_ts
from app.json_state import JsonStateStore, store_active_prediction_evaluation
from app.once import _effective_depletion_rate, _schedule_json_departure_reminders, process_json_due_notifications, run_json_once
from app.predictor import METHOD_DEFAULT, build_prediction


class FakeClient:
    def __init__(self, quantity: int) -> None:
        self.quantity = quantity

    def fetch_json(self):
        return {
            "stocks": {
                "uni": {
                    "stocks": [
                        {"id": 206, "name": "Xanax", "quantity": self.quantity, "cost": 1},
                    ]
                }
            }
        }


def make_config(tmp_path: Path) -> Config:
    return Config(
        yata_url="https://yata.yt/api/v1/travel/export/",
        item_id=206,
        country="UK",
        country_aliases=("UK", "United Kingdom", "uni"),
        poll_seconds=60,
        discord_webhook_url=None,
        database_path=tmp_path / "local.sqlite3",
        state_backend="json",
        state_path=tmp_path / "state.json",
        github_actions_delay_buffer_minutes=5,
        ping_lead_minutes=0,
        enable_airstrip_pings=True,
        enable_business_class_pings=True,
        airstrip_duration_minutes=111,
        business_class_duration_minutes=48,
        airstrip_target_restock_cycle=1,
        business_class_target_restock_cycle=1,
        default_depletion_rate_per_minute=265,
        restock_backfill_rate_multiplier=4,
        depletion_rate_history_window=20,
        min_depletion_rate_sample_seconds=90,
        depletion_rate_min_multiplier=0.25,
        depletion_rate_max_multiplier=1.75,
        prediction_interval_min_ticks=80,
        prediction_interval_max_ticks=180,
        prediction_interval_mad_threshold=3.5,
        prediction_accuracy_tolerance_ticks=10,
        prediction_history_window=10,
        log_level="INFO",
    )


def test_monitor_once_cli_exits_after_one_cycle(monkeypatch, tmp_path) -> None:
    config = make_config(tmp_path)
    calls = []

    monkeypatch.setattr(monitor, "load_config", lambda: config)
    monkeypatch.setattr(monitor, "configure_logging", lambda _level: None)
    monkeypatch.setattr(monitor, "run_once_command", lambda _config: calls.append(_config) or 0)

    assert monitor.main(["--once"]) == 0
    assert calls == [config]


def test_json_once_prevents_duplicate_restock_notifications(monkeypatch, tmp_path) -> None:
    config = make_config(tmp_path)
    store = JsonStateStore(config.state_path)
    state = store.load()
    state["last_quantity"] = 0
    state["last_observed_at"] = "2026-05-18T12:00:00+00:00"
    store.save(state)

    fixed_now = datetime(2026, 5, 18, 12, 7, 12, tzinfo=timezone.utc)
    sent_messages = []
    monkeypatch.setattr("app.once.utc_now", lambda: fixed_now)
    monkeypatch.setattr("app.once.send_webhook", lambda _url, content: sent_messages.append(content) or (True, None))

    run_json_once(config, FakeClient(quantity=10))
    run_json_once(config, FakeClient(quantity=10))

    final_state = store.load()
    assert len(sent_messages) == 1
    assert final_state["last_quantity"] == 10
    assert final_state["depletion_rate_per_minute"] == 265
    assert final_state["last_restock_normalized_at"] == "2026-05-18T12:04:00+00:00"
    assert final_state["last_notified_restock_normalized_at"] == "2026-05-18T12:04:00+00:00"


def test_json_restock_message_predicts_next_cycle_from_current_depletion(monkeypatch, tmp_path) -> None:
    config = make_config(tmp_path)
    store = JsonStateStore(config.state_path)
    state = store.load()
    state["last_quantity"] = 0
    state["last_observed_at"] = "2026-05-19T12:18:00+00:00"
    state["last_estimated_depleted_at"] = "2026-05-19T10:33:00+00:00"
    state["depletion_to_restock_interval_ticks"] = [113, 108]
    store.save(state)

    fixed_now = datetime(2026, 5, 19, 12, 24, 0, tzinfo=timezone.utc)
    sent_messages = []
    monkeypatch.setattr("app.once.utc_now", lambda: fixed_now)
    monkeypatch.setattr("app.once.send_webhook", lambda _url, content: sent_messages.append(content) or (True, None))

    run_json_once(config, FakeClient(quantity=2100))

    final_state = store.load()
    expected_next_restock = datetime(2026, 5, 19, 14, 22, tzinfo=timezone.utc)
    old_anchor_prediction = datetime(2026, 5, 19, 14, 11, tzinfo=timezone.utc)
    assert final_state["depletion_to_restock_interval_ticks"] == [113, 108, 110]
    assert final_state["last_predicted_restock_at"] == "2026-05-19T14:22:00+00:00"
    assert final_state["active_prediction_evaluation"]["predicted_restock_at"] == "2026-05-19T14:22:00+00:00"
    assert final_state["active_prediction_evaluation"]["window_start_at"] == "2026-05-19T14:12:00+00:00"
    assert final_state["active_prediction_evaluation"]["window_end_at"] == "2026-05-19T14:32:00+00:00"
    assert len(sent_messages) == 1
    assert discord_ts(expected_next_restock, "F") in sent_messages[0]
    assert discord_ts(old_anchor_prediction, "F") not in sent_messages[0]
    assert "window_start_at" not in sent_messages[0]
    assert "prediction_accuracy" not in sent_messages[0]
    assert final_state["pending_notifications"] == []


def test_json_depletion_schedules_only_enabled_departure_pings(monkeypatch, tmp_path) -> None:
    config = replace(make_config(tmp_path), enable_business_class_pings=False)
    store = JsonStateStore(config.state_path)
    state = store.load()
    state["last_quantity"] = 100
    state["last_observed_at"] = "2026-05-19T12:18:00+00:00"
    state["last_positive_observation"] = {
        "observed_at": "2026-05-19T12:18:00+00:00",
        "item_id": 206,
        "country": "UK",
        "quantity": 100,
    }
    store.save(state)

    fixed_now = datetime(2026, 5, 19, 12, 20, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("app.once.utc_now", lambda: fixed_now)
    monkeypatch.setattr("app.once.send_webhook", lambda _url, _content: (True, None))

    run_json_once(config, FakeClient(quantity=0))

    final_state = store.load()
    assert len(final_state["pending_notifications"]) == 1
    assert final_state["pending_notifications"][0]["notification_type"] == "AIRSTRIP_DEPARTURE_REMINDER"
    assert final_state["active_prediction_evaluation"]["predicted_restock_at"] == "2026-05-19T14:24:00+00:00"
    assert final_state["active_prediction_evaluation"]["window_start_at"] == "2026-05-19T14:14:00+00:00"
    assert final_state["active_prediction_evaluation"]["window_end_at"] == "2026-05-19T14:34:00+00:00"


def test_json_japan_airstrip_schedules_second_restock_but_business_schedules_first(monkeypatch, tmp_path) -> None:
    config = replace(
        make_config(tmp_path),
        country="Japan",
        country_aliases=("Japan", "Tokyo", "jap", "jpn"),
        airstrip_duration_minutes=158,
        business_class_duration_minutes=68,
        airstrip_target_restock_cycle=2,
        business_class_target_restock_cycle=1,
    )
    store = JsonStateStore(config.state_path)
    state = store.load()
    state["last_quantity"] = 100
    state["last_observed_at"] = "2026-05-19T12:18:00+00:00"
    state["last_positive_observation"] = {
        "observed_at": "2026-05-19T12:18:00+00:00",
        "item_id": 206,
        "country": "Japan",
        "quantity": 100,
    }
    store.save(state)

    fixed_now = datetime(2026, 5, 19, 12, 20, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("app.once.utc_now", lambda: fixed_now)
    monkeypatch.setattr("app.once.send_webhook", lambda _url, _content: (True, None))

    class JapanClient:
        def fetch_json(self):
            return {
                "stocks": {
                    "jap": {
                        "stocks": [
                            {"id": 206, "name": "Xanax", "quantity": 0, "cost": 1},
                        ]
                    }
                }
            }

    run_json_once(config, JapanClient())

    final_state = store.load()
    notifications = sorted(final_state["pending_notifications"], key=lambda value: value["notification_type"])
    airstrip = next(value for value in notifications if value["notification_type"] == "AIRSTRIP_DEPARTURE_REMINDER")
    business = next(value for value in notifications if value["notification_type"] == "BUSINESS_DEPARTURE_REMINDER")

    assert final_state["last_predicted_restock_at"] == "2026-05-19T14:24:00+00:00"
    assert airstrip["prediction"]["airstrip_target_restock_at"] == "2026-05-19T16:39:00+00:00"
    assert airstrip["target_time"] == "2026-05-19T13:56:00+00:00"
    assert business["prediction"]["business_class_target_restock_at"] == "2026-05-19T14:24:00+00:00"
    assert business["target_time"] == "2026-05-19T13:11:00+00:00"


def test_json_depletion_commits_pending_drpm_samples_to_restock_bucket(monkeypatch, tmp_path) -> None:
    config = replace(make_config(tmp_path), enable_airstrip_pings=False, enable_business_class_pings=False)
    store = JsonStateStore(config.state_path)
    state = store.load()
    state["last_quantity"] = 1000
    state["last_observed_at"] = "2026-05-19T10:00:00+00:00"
    state["last_restock_normalized_at"] = "2026-05-19T17:00:00+00:00"
    state["last_positive_observation"] = {
        "observed_at": "2026-05-19T10:00:00+00:00",
        "item_id": 206,
        "country": "UK",
        "quantity": 1000,
    }
    store.save(state)

    times = iter(
        [
            datetime(2026, 5, 19, 10, 2, 0, tzinfo=timezone.utc),
            datetime(2026, 5, 19, 10, 2, 0, tzinfo=timezone.utc),
            datetime(2026, 5, 19, 10, 2, 0, tzinfo=timezone.utc),
            datetime(2026, 5, 19, 10, 4, 0, tzinfo=timezone.utc),
            datetime(2026, 5, 19, 10, 4, 0, tzinfo=timezone.utc),
            datetime(2026, 5, 19, 10, 4, 0, tzinfo=timezone.utc),
            datetime(2026, 5, 19, 10, 4, 0, tzinfo=timezone.utc),
            datetime(2026, 5, 19, 10, 4, 0, tzinfo=timezone.utc),
        ]
    )
    monkeypatch.setattr("app.once.utc_now", lambda: next(times))
    monkeypatch.setattr("app.once.send_webhook", lambda _url, _content: (True, None))

    run_json_once(config, FakeClient(quantity=800))
    after_drop = store.load()
    assert after_drop["current_cycle_depletion_rate_samples"] == [100.0]
    assert after_drop["depletion_rate_history"][HIGH_TRAFFIC] == []

    run_json_once(config, FakeClient(quantity=0))

    final_state = store.load()
    assert final_state["current_cycle_depletion_rate_samples"] == []
    assert final_state["depletion_rate_history"][HIGH_TRAFFIC] == [100.0]
    assert final_state["depletion_rate_history"][LOW_TRAFFIC] == []
    assert final_state["depletion_rate_history"][MID_TRAFFIC] == []


def test_json_restock_evaluates_active_prediction_as_correct(monkeypatch, tmp_path) -> None:
    config = make_config(tmp_path)
    store = JsonStateStore(config.state_path)
    state = store.load()
    state["last_quantity"] = 0
    state["last_observed_at"] = "2026-05-18T12:00:00+00:00"
    prediction = build_prediction(
        event_id=0,
        predicted_restock_at=datetime(2026, 5, 18, 12, 4, tzinfo=timezone.utc),
        interval_ticks=125,
        method=METHOD_DEFAULT,
    )
    store_active_prediction_evaluation(
        state,
        prediction,
        tolerance_ticks=10,
        created_at=datetime(2026, 5, 18, 10, 0, tzinfo=timezone.utc),
        anchor_at=datetime(2026, 5, 18, 9, 59, tzinfo=timezone.utc),
    )
    store.save(state)

    fixed_now = datetime(2026, 5, 18, 12, 7, 12, tzinfo=timezone.utc)
    sent_messages = []
    monkeypatch.setattr("app.once.utc_now", lambda: fixed_now)
    monkeypatch.setattr("app.once.send_webhook", lambda _url, content: sent_messages.append(content) or (True, None))

    run_json_once(config, FakeClient(quantity=10))

    final_state = store.load()
    assert final_state["prediction_evaluation_history"][0]["correct"] is True
    assert final_state["prediction_evaluation_history"][0]["error_ticks"] == 0
    assert final_state["prediction_accuracy"] == {
        "evaluated_count": 1,
        "correct_count": 1,
        "accuracy": 1.0,
        "tolerance_ticks": 10,
        "last_error_ticks": 0,
    }
    assert final_state["active_prediction_evaluation"] is not None
    assert "window_start_at" not in sent_messages[0]
    assert "prediction_accuracy" not in sent_messages[0]


def test_json_restock_evaluates_active_prediction_as_incorrect(monkeypatch, tmp_path) -> None:
    config = make_config(tmp_path)
    store = JsonStateStore(config.state_path)
    state = store.load()
    state["last_quantity"] = 0
    state["last_observed_at"] = "2026-05-18T12:00:00+00:00"
    prediction = build_prediction(
        event_id=0,
        predicted_restock_at=datetime(2026, 5, 18, 11, 50, tzinfo=timezone.utc),
        interval_ticks=125,
        method=METHOD_DEFAULT,
    )
    store_active_prediction_evaluation(
        state,
        prediction,
        tolerance_ticks=10,
        created_at=datetime(2026, 5, 18, 10, 0, tzinfo=timezone.utc),
    )
    store.save(state)

    fixed_now = datetime(2026, 5, 18, 12, 7, 12, tzinfo=timezone.utc)
    monkeypatch.setattr("app.once.utc_now", lambda: fixed_now)
    monkeypatch.setattr("app.once.send_webhook", lambda _url, _content: (True, None))

    run_json_once(config, FakeClient(quantity=10))

    final_state = store.load()
    assert final_state["prediction_evaluation_history"][0]["correct"] is False
    assert final_state["prediction_evaluation_history"][0]["error_ticks"] == 14
    assert final_state["prediction_accuracy"]["evaluated_count"] == 1
    assert final_state["prediction_accuracy"]["correct_count"] == 0
    assert final_state["prediction_accuracy"]["accuracy"] == 0.0
    assert final_state["prediction_accuracy"]["last_error_ticks"] == 14


def test_effective_depletion_rate_uses_observation_time_bucket(tmp_path) -> None:
    config = make_config(tmp_path)
    state = JsonStateStore(config.state_path).load()
    state["depletion_rate_history"] = {
        LOW_TRAFFIC: [300, 310, 320],
        MID_TRAFFIC: [240, 250, 260],
        HIGH_TRAFFIC: [400, 410, 420],
    }

    assert _effective_depletion_rate(config, state, datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)) == 250
    assert _effective_depletion_rate(config, state, datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc)) == 410


def test_effective_depletion_rate_empty_active_bucket_falls_back_to_default(tmp_path) -> None:
    config = make_config(tmp_path)
    state = JsonStateStore(config.state_path).load()
    state["depletion_rate_history"] = {
        LOW_TRAFFIC: [300, 310, 320],
        MID_TRAFFIC: [],
        HIGH_TRAFFIC: [400, 410, 420],
    }

    assert _effective_depletion_rate(config, state, datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)) == 265


def test_json_late_departure_ping_sends_when_latest_safe_is_still_future(monkeypatch, tmp_path) -> None:
    config = replace(make_config(tmp_path), enable_business_class_pings=False)
    state = JsonStateStore(config.state_path).load()
    prediction = build_prediction(
        event_id=0,
        predicted_restock_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        interval_ticks=125,
        method=METHOD_DEFAULT,
        departure_buffer_minutes=5,
        ping_lead_minutes=0,
    )
    now = datetime(2026, 1, 1, 10, 5, tzinfo=timezone.utc)
    sent_messages = []
    monkeypatch.setattr("app.once.send_webhook", lambda _url, content: sent_messages.append(content) or (True, None))

    _schedule_json_departure_reminders(config, state, prediction, restock_key="test", now=now)
    process_json_due_notifications(config, state, now=now)

    assert len(sent_messages) == 1
    assert "Airstrip Departure Reminder" in sent_messages[0]
    assert state["pending_notifications"] == []
    assert state["sent_notification_keys"] == []


def test_json_due_notification_cleanup_keeps_unsent_pending(monkeypatch, tmp_path) -> None:
    config = replace(make_config(tmp_path), enable_business_class_pings=False)
    state = JsonStateStore(config.state_path).load()
    prediction = build_prediction(
        event_id=0,
        predicted_restock_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        interval_ticks=125,
        method=METHOD_DEFAULT,
        departure_buffer_minutes=5,
        ping_lead_minutes=0,
    )
    before_ping = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("app.once.send_webhook", lambda _url, _content: (True, None))

    _schedule_json_departure_reminders(config, state, prediction, restock_key="test", now=before_ping)
    process_json_due_notifications(config, state, now=before_ping)

    assert len(state["pending_notifications"]) == 1
    assert state["pending_notifications"][0]["status"] == "PENDING"


def test_json_due_notification_cleanup_prunes_completed_legacy_entries(monkeypatch, tmp_path) -> None:
    config = replace(make_config(tmp_path), enable_business_class_pings=False)
    state = JsonStateStore(config.state_path).load()
    prediction = build_prediction(
        event_id=0,
        predicted_restock_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        interval_ticks=125,
        method=METHOD_DEFAULT,
        departure_buffer_minutes=5,
        ping_lead_minutes=0,
    )
    before_ping = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    now = datetime(2026, 1, 1, 10, 10, tzinfo=timezone.utc)
    monkeypatch.setattr("app.once.send_webhook", lambda _url, _content: (True, None))

    _schedule_json_departure_reminders(config, state, prediction, restock_key="test", now=before_ping)
    completed = {
        **state["pending_notifications"][0],
        "status": "SENT",
        "sent_at": "2026-01-01T10:04:23+00:00",
        "error_message": None,
    }
    state["pending_notifications"] = [
        completed,
        {
            **completed,
            "key": "AIRSTRIP_DEPARTURE_REMINDER:future:2026-01-01T10:30:00+00:00",
            "target_time": "2026-01-01T10:30:00+00:00",
            "status": "PENDING",
            "sent_at": None,
        },
    ]

    process_json_due_notifications(config, state, now=now)

    assert len(state["pending_notifications"]) == 1
    assert state["pending_notifications"][0]["key"] == "AIRSTRIP_DEPARTURE_REMINDER:future:2026-01-01T10:30:00+00:00"


def test_json_late_departure_ping_skips_after_latest_safe_passed(tmp_path) -> None:
    config = replace(make_config(tmp_path), enable_business_class_pings=False)
    state = JsonStateStore(config.state_path).load()
    prediction = build_prediction(
        event_id=0,
        predicted_restock_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        interval_ticks=125,
        method=METHOD_DEFAULT,
        departure_buffer_minutes=5,
        ping_lead_minutes=0,
    )
    now = datetime(2026, 1, 1, 10, 10, tzinfo=timezone.utc)

    _schedule_json_departure_reminders(config, state, prediction, restock_key="test", now=now)

    assert state["pending_notifications"] == []
    assert state["sent_notification_keys"] == []
