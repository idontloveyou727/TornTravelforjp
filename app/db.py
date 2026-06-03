from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models import Prediction, StockEvent, StockObservation


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def encode_dt(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def decode_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row

    def close(self) -> None:
        self.connection.close()

    def init_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS stock_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                observed_at TEXT NOT NULL,
                item_id INTEGER NOT NULL,
                country TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                raw_payload_json TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS stock_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                item_id INTEGER NOT NULL,
                country TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                normalized_at TEXT,
                previous_quantity INTEGER,
                current_quantity INTEGER NOT NULL,
                source_delay_seconds INTEGER,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                based_on_restock_event_id INTEGER NOT NULL,
                predicted_restock_at TEXT NOT NULL,
                predicted_interval_ticks INTEGER NOT NULL,
                prediction_method TEXT NOT NULL,
                airstrip_departure_at TEXT NOT NULL,
                business_departure_at TEXT NOT NULL,
                airstrip_latest_departure_at TEXT,
                business_latest_departure_at TEXT,
                airstrip_ping_at TEXT NOT NULL,
                business_ping_at TEXT NOT NULL,
                airstrip_target_restock_at TEXT,
                business_class_target_restock_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (based_on_restock_event_id) REFERENCES stock_events(id)
            );

            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                notification_type TEXT NOT NULL,
                related_restock_event_id INTEGER,
                related_prediction_id INTEGER,
                target_time TEXT NOT NULL,
                sent_at TEXT,
                status TEXT NOT NULL,
                error_message TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_observations_latest
                ON stock_observations(item_id, country, observed_at);
            CREATE INDEX IF NOT EXISTS idx_events_restock
                ON stock_events(event_type, item_id, country, normalized_at);
            CREATE INDEX IF NOT EXISTS idx_notifications_due
                ON notifications(status, target_time);
            CREATE INDEX IF NOT EXISTS idx_notifications_duplicate
                ON notifications(notification_type, related_restock_event_id, related_prediction_id);
            """
        )
        self._ensure_prediction_latest_columns()
        self.connection.commit()

    def _ensure_prediction_latest_columns(self) -> None:
        columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(predictions)").fetchall()}
        if "airstrip_latest_departure_at" not in columns:
            self.connection.execute("ALTER TABLE predictions ADD COLUMN airstrip_latest_departure_at TEXT")
        if "business_latest_departure_at" not in columns:
            self.connection.execute("ALTER TABLE predictions ADD COLUMN business_latest_departure_at TEXT")
        if "airstrip_target_restock_at" not in columns:
            self.connection.execute("ALTER TABLE predictions ADD COLUMN airstrip_target_restock_at TEXT")
        if "business_class_target_restock_at" not in columns:
            self.connection.execute("ALTER TABLE predictions ADD COLUMN business_class_target_restock_at TEXT")
        self.connection.execute(
            """
            UPDATE predictions
            SET airstrip_latest_departure_at = airstrip_departure_at
            WHERE airstrip_latest_departure_at IS NULL
            """
        )
        self.connection.execute(
            """
            UPDATE predictions
            SET business_latest_departure_at = business_departure_at
            WHERE business_latest_departure_at IS NULL
            """
        )
        self.connection.execute(
            """
            UPDATE predictions
            SET airstrip_target_restock_at = predicted_restock_at
            WHERE airstrip_target_restock_at IS NULL
            """
        )
        self.connection.execute(
            """
            UPDATE predictions
            SET business_class_target_restock_at = predicted_restock_at
            WHERE business_class_target_restock_at IS NULL
            """
        )

    def insert_observation(self, observation: StockObservation) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO stock_observations
                (observed_at, item_id, country, quantity, raw_payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                encode_dt(observation.observed_at),
                observation.item_id,
                observation.country,
                observation.quantity,
                json.dumps(observation.raw_payload, sort_keys=True) if observation.raw_payload is not None else None,
                encode_dt(utc_now()),
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def latest_observation(self, item_id: int, country: str) -> StockObservation | None:
        row = self.connection.execute(
            """
            SELECT * FROM stock_observations
            WHERE item_id = ? AND country = ?
            ORDER BY observed_at DESC, id DESC
            LIMIT 1
            """,
            (item_id, country),
        ).fetchone()
        if row is None:
            return None
        return StockObservation(
            observed_at=decode_dt(row["observed_at"]),
            item_id=int(row["item_id"]),
            country=str(row["country"]),
            quantity=int(row["quantity"]),
            raw_payload=json.loads(row["raw_payload_json"]) if row["raw_payload_json"] else None,
        )

    def insert_event(self, event: StockEvent) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO stock_events
                (event_type, item_id, country, observed_at, normalized_at,
                 previous_quantity, current_quantity, source_delay_seconds, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_type,
                event.item_id,
                event.country,
                encode_dt(event.observed_at),
                encode_dt(event.normalized_at) if event.normalized_at else None,
                event.previous_quantity,
                event.current_quantity,
                event.source_delay_seconds,
                encode_dt(utc_now()),
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def recent_restock_times(self, item_id: int, country: str, limit: int) -> list[datetime]:
        rows = self.connection.execute(
            """
            SELECT normalized_at FROM stock_events
            WHERE event_type = 'RESTOCK' AND item_id = ? AND country = ? AND normalized_at IS NOT NULL
            ORDER BY normalized_at DESC, id DESC
            LIMIT ?
            """,
            (item_id, country, limit),
        ).fetchall()
        return [decode_dt(row["normalized_at"]) for row in reversed(rows)]

    def insert_prediction(self, prediction: Prediction) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO predictions
                (based_on_restock_event_id, predicted_restock_at, predicted_interval_ticks,
                 prediction_method, airstrip_departure_at, business_departure_at,
                 airstrip_latest_departure_at, business_latest_departure_at,
                 airstrip_ping_at, business_ping_at,
                 airstrip_target_restock_at, business_class_target_restock_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prediction.based_on_restock_event_id,
                encode_dt(prediction.predicted_restock_at),
                prediction.predicted_interval_ticks,
                prediction.prediction_method,
                encode_dt(prediction.airstrip_departure_at),
                encode_dt(prediction.business_departure_at),
                encode_dt(prediction.airstrip_latest_departure_at),
                encode_dt(prediction.business_latest_departure_at),
                encode_dt(prediction.airstrip_ping_at),
                encode_dt(prediction.business_ping_at),
                encode_dt(prediction.effective_airstrip_target_restock_at),
                encode_dt(prediction.effective_business_class_target_restock_at),
                encode_dt(utc_now()),
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def get_prediction(self, prediction_id: int) -> Prediction:
        row = self.connection.execute("SELECT * FROM predictions WHERE id = ?", (prediction_id,)).fetchone()
        if row is None:
            raise KeyError(f"Prediction not found: {prediction_id}")
        return Prediction(
            based_on_restock_event_id=int(row["based_on_restock_event_id"]),
            predicted_restock_at=decode_dt(row["predicted_restock_at"]),
            predicted_interval_ticks=int(row["predicted_interval_ticks"]),
            prediction_method=str(row["prediction_method"]),
            airstrip_departure_at=decode_dt(row["airstrip_departure_at"]),
            business_departure_at=decode_dt(row["business_departure_at"]),
            airstrip_latest_departure_at=decode_dt(row["airstrip_latest_departure_at"] or row["airstrip_departure_at"]),
            business_latest_departure_at=decode_dt(row["business_latest_departure_at"] or row["business_departure_at"]),
            airstrip_ping_at=decode_dt(row["airstrip_ping_at"]),
            business_ping_at=decode_dt(row["business_ping_at"]),
            airstrip_target_restock_at=decode_dt(row["airstrip_target_restock_at"] or row["predicted_restock_at"]),
            business_class_target_restock_at=decode_dt(
                row["business_class_target_restock_at"] or row["predicted_restock_at"]
            ),
        )

    def get_event(self, event_id: int) -> StockEvent:
        row = self.connection.execute("SELECT * FROM stock_events WHERE id = ?", (event_id,)).fetchone()
        if row is None:
            raise KeyError(f"Event not found: {event_id}")
        return StockEvent(
            event_type=str(row["event_type"]),
            item_id=int(row["item_id"]),
            country=str(row["country"]),
            observed_at=decode_dt(row["observed_at"]),
            normalized_at=decode_dt(row["normalized_at"]) if row["normalized_at"] else None,
            previous_quantity=int(row["previous_quantity"]) if row["previous_quantity"] is not None else None,
            current_quantity=int(row["current_quantity"]),
            source_delay_seconds=int(row["source_delay_seconds"]) if row["source_delay_seconds"] is not None else None,
        )

    def create_notification_once(
        self,
        *,
        notification_type: str,
        related_restock_event_id: int | None,
        related_prediction_id: int | None,
        target_time: datetime,
        status: str = "PENDING",
        error_message: str | None = None,
    ) -> int | None:
        existing = self.connection.execute(
            """
            SELECT id FROM notifications
            WHERE notification_type = ?
              AND COALESCE(related_restock_event_id, -1) = COALESCE(?, -1)
              AND COALESCE(related_prediction_id, -1) = COALESCE(?, -1)
            LIMIT 1
            """,
            (notification_type, related_restock_event_id, related_prediction_id),
        ).fetchone()
        if existing:
            return None

        cursor = self.connection.execute(
            """
            INSERT INTO notifications
                (notification_type, related_restock_event_id, related_prediction_id,
                 target_time, sent_at, status, error_message, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                notification_type,
                related_restock_event_id,
                related_prediction_id,
                encode_dt(target_time),
                None,
                status,
                error_message,
                encode_dt(utc_now()),
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def due_notifications(self, now: datetime) -> list[sqlite3.Row]:
        return self.connection.execute(
            """
            SELECT * FROM notifications
            WHERE status = 'PENDING' AND target_time <= ?
            ORDER BY target_time ASC, id ASC
            """,
            (encode_dt(now),),
        ).fetchall()

    def mark_notification(self, notification_id: int, status: str, error_message: str | None = None) -> None:
        sent_at = encode_dt(utc_now()) if status == "SENT" else None
        self.connection.execute(
            """
            UPDATE notifications
            SET status = ?, sent_at = ?, error_message = ?
            WHERE id = ?
            """,
            (status, sent_at, error_message, notification_id),
        )
        self.connection.commit()
