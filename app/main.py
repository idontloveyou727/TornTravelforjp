from __future__ import annotations

import logging
import signal
import threading
from datetime import timezone

from app.config import load_config
from app.db import Database, utc_now
from app.detector import EVENT_RESTOCK, detect_stock_event
from app.logging_config import configure_logging
from app.parser import extract_stock_observation
from app.predictor import predict_next_restock
from app.scheduler import create_notifications_for_restock, process_due_notifications
from app.yata_client import YataClient

LOGGER = logging.getLogger(__name__)


def main() -> None:
    run_forever()


def run_forever() -> None:
    config = load_config()
    configure_logging(config.log_level)
    LOGGER.info("Starting YATA restock monitor config=%s", config.safe_summary())

    stop_event = threading.Event()
    _install_signal_handlers(stop_event)

    db = Database(config.database_path)
    db.init_schema()
    client = YataClient(config.yata_url)

    try:
        while not stop_event.is_set():
            try:
                run_sqlite_cycle(config, db, client)
            except Exception:
                LOGGER.exception("Monitor loop failed; will retry on next poll")
                try:
                    process_due_notifications(
                        db,
                        config.discord_webhook_url,
                        config.ping_lead_minutes,
                        country=config.country,
                        enable_airstrip_pings=config.enable_airstrip_pings,
                        enable_business_class_pings=config.enable_business_class_pings,
                    )
                except Exception:
                    LOGGER.exception("Failed to process due notifications after monitor loop error")

            stop_event.wait(config.poll_seconds)
    finally:
        db.close()
        LOGGER.info("YATA restock monitor stopped")


def run_sqlite_cycle(config, db: Database, client: YataClient) -> None:
    payload = client.fetch_json()
    observed_at = utc_now().astimezone(timezone.utc)
    previous = db.latest_observation(config.item_id, config.country)
    observation = extract_stock_observation(
        payload,
        item_id=config.item_id,
        country=config.country,
        country_aliases=config.country_aliases,
        observed_at=observed_at,
    )
    db.insert_observation(observation)
    LOGGER.info(
        "Saved stock observation item_id=%s country=%s quantity=%s observed_at=%s",
        observation.item_id,
        observation.country,
        observation.quantity,
        observation.observed_at.isoformat(),
    )

    event = detect_stock_event(previous, observation)
    if event is not None:
        event_id = db.insert_event(event)
        LOGGER.info(
            "Saved stock event id=%s type=%s previous_quantity=%s current_quantity=%s",
            event_id,
            event.event_type,
            event.previous_quantity,
            event.current_quantity,
        )
        if event.event_type == EVENT_RESTOCK and event.normalized_at is not None:
            historical_times = db.recent_restock_times(config.item_id, config.country, config.prediction_history_window + 1)
            prediction = predict_next_restock(
                current_restock_event_id=event_id,
                current_normalized_restock_at=event.normalized_at,
                historical_restock_times=historical_times,
                history_window=config.prediction_history_window,
                departure_buffer_minutes=config.github_actions_delay_buffer_minutes,
                ping_lead_minutes=config.ping_lead_minutes,
                airstrip_duration_minutes=config.airstrip_duration_minutes,
                business_class_duration_minutes=config.business_class_duration_minutes,
                airstrip_target_restock_cycle=config.airstrip_target_restock_cycle,
                business_class_target_restock_cycle=config.business_class_target_restock_cycle,
                projected_depletion_rate_per_minute=config.default_depletion_rate_per_minute,
            )
            prediction_id = db.insert_prediction(prediction)
            LOGGER.info(
                "Saved prediction id=%s predicted_restock_at=%s interval_ticks=%s method=%s",
                prediction_id,
                prediction.predicted_restock_at.isoformat(),
                prediction.predicted_interval_ticks,
                prediction.prediction_method,
            )
            create_notifications_for_restock(
                db,
                event_id=event_id,
                prediction_id=prediction_id,
                prediction=prediction,
                now=utc_now(),
                enable_airstrip_pings=config.enable_airstrip_pings,
                enable_business_class_pings=config.enable_business_class_pings,
            )
    else:
        LOGGER.info("No stock event detected; quantity unchanged at %s", observation.quantity)

    process_due_notifications(
        db,
        config.discord_webhook_url,
        config.ping_lead_minutes,
        country=config.country,
        enable_airstrip_pings=config.enable_airstrip_pings,
        enable_business_class_pings=config.enable_business_class_pings,
    )


def _install_signal_handlers(stop_event: threading.Event) -> None:
    def handle_signal(signum, _frame) -> None:
        LOGGER.info("Received shutdown signal signum=%s", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)


if __name__ == "__main__":
    main()
