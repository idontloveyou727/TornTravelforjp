from __future__ import annotations

import logging
from datetime import datetime

from app.db import Database, decode_dt, utc_now
from app.discord_webhook import (
    format_airstrip_reminder,
    format_business_reminder,
    format_restock_detected,
    send_webhook,
)
from app.models import Prediction, StockEvent

LOGGER = logging.getLogger(__name__)

RESTOCK_DETECTED = "RESTOCK_DETECTED"
AIRSTRIP_DEPARTURE_REMINDER = "AIRSTRIP_DEPARTURE_REMINDER"
BUSINESS_DEPARTURE_REMINDER = "BUSINESS_DEPARTURE_REMINDER"


def create_notifications_for_restock(
    db: Database,
    *,
    event_id: int,
    prediction_id: int,
    prediction: Prediction,
    now: datetime,
    enable_airstrip_pings: bool = True,
    enable_business_class_pings: bool = True,
) -> None:
    db.create_notification_once(
        notification_type=RESTOCK_DETECTED,
        related_restock_event_id=event_id,
        related_prediction_id=prediction_id,
        target_time=now,
    )
    if enable_airstrip_pings:
        _create_departure_notification(
            db,
            notification_type=AIRSTRIP_DEPARTURE_REMINDER,
            event_id=event_id,
            prediction_id=prediction_id,
            target_time=prediction.airstrip_ping_at,
            latest_safe_time=prediction.airstrip_latest_departure_at,
            now=now,
        )
    if enable_business_class_pings:
        _create_departure_notification(
            db,
            notification_type=BUSINESS_DEPARTURE_REMINDER,
            event_id=event_id,
            prediction_id=prediction_id,
            target_time=prediction.business_ping_at,
            latest_safe_time=prediction.business_latest_departure_at,
            now=now,
        )


def process_due_notifications(
    db: Database,
    webhook_url: str | None,
    ping_lead_minutes: int = 0,
    *,
    country: str | None = None,
    enable_airstrip_pings: bool = True,
    enable_business_class_pings: bool = True,
) -> None:
    for row in db.due_notifications(utc_now()):
        notification_id = int(row["id"])
        notification_type = str(row["notification_type"])
        if _notification_disabled(
            notification_type,
            enable_airstrip_pings=enable_airstrip_pings,
            enable_business_class_pings=enable_business_class_pings,
        ):
            db.mark_notification(notification_id, "SKIPPED", "Departure reminder type disabled by configuration")
            LOGGER.info("Skipped disabled departure reminder id=%s type=%s", notification_id, notification_type)
            continue
        try:
            content = _format_notification(
                db,
                notification_type,
                row,
                ping_lead_minutes,
                country=country,
                enable_airstrip_pings=enable_airstrip_pings,
                enable_business_class_pings=enable_business_class_pings,
            )
            ok, error = send_webhook(webhook_url, content)
            db.mark_notification(notification_id, "SENT" if ok else "FAILED", error)
        except Exception as exc:
            LOGGER.exception("Failed to process notification id=%s", notification_id)
            db.mark_notification(notification_id, "FAILED", str(exc))


def _create_departure_notification(
    db: Database,
    *,
    notification_type: str,
    event_id: int,
    prediction_id: int,
    target_time: datetime,
    latest_safe_time: datetime,
    now: datetime,
) -> None:
    if target_time <= now and latest_safe_time <= now:
        db.create_notification_once(
            notification_type=notification_type,
            related_restock_event_id=event_id,
            related_prediction_id=prediction_id,
            target_time=target_time,
            status="SKIPPED",
            error_message="Departure reminder target time was already in the past",
        )
        LOGGER.info("Skipped missed departure reminder type=%s prediction_id=%s", notification_type, prediction_id)
        return

    db.create_notification_once(
        notification_type=notification_type,
        related_restock_event_id=event_id,
        related_prediction_id=prediction_id,
        target_time=target_time,
    )


def _notification_disabled(
    notification_type: str,
    *,
    enable_airstrip_pings: bool,
    enable_business_class_pings: bool,
) -> bool:
    if notification_type == AIRSTRIP_DEPARTURE_REMINDER:
        return not enable_airstrip_pings
    if notification_type == BUSINESS_DEPARTURE_REMINDER:
        return not enable_business_class_pings
    return False


def _format_notification(
    db: Database,
    notification_type: str,
    row,
    ping_lead_minutes: int = 0,
    *,
    country: str | None = None,
    enable_airstrip_pings: bool = True,
    enable_business_class_pings: bool = True,
) -> str:
    prediction_id = int(row["related_prediction_id"])
    event_id = int(row["related_restock_event_id"]) if row["related_restock_event_id"] is not None else None
    prediction = db.get_prediction(prediction_id)

    if notification_type == RESTOCK_DETECTED:
        if event_id is None:
            raise ValueError("Restock notification missing related event id")
        event = db.get_event(event_id)
        return format_restock_detected(
            event,
            prediction,
            prediction_id,
            include_airstrip=enable_airstrip_pings,
            include_business=enable_business_class_pings,
        )
    if notification_type == AIRSTRIP_DEPARTURE_REMINDER:
        return format_airstrip_reminder(prediction, ping_lead_minutes, country=country)
    if notification_type == BUSINESS_DEPARTURE_REMINDER:
        return format_business_reminder(prediction, ping_lead_minutes, country=country)
    raise ValueError(f"Unknown notification type: {notification_type}")
