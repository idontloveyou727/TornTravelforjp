from __future__ import annotations

import logging
import time
from datetime import datetime

import requests

from app.models import Prediction, StockEvent

LOGGER = logging.getLogger(__name__)


class DiscordWebhookError(RuntimeError):
    pass


def discord_ts(dt: datetime, style: str = "F") -> str:
    unix = int(dt.timestamp())
    return f"<t:{unix}:{style}>"


def send_webhook(url: str | None, content: str, *, max_attempts: int = 3) -> tuple[bool, str | None]:
    if not url:
        LOGGER.info("Discord webhook disabled; dry-run message content=%s", content)
        return True, None

    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.post(url, json={"content": content}, timeout=15)
        except requests.RequestException as exc:
            LOGGER.warning("Discord webhook request failed attempt=%s/%s error=%s", attempt, max_attempts, exc)
            if attempt < max_attempts:
                time.sleep(min(30.0, 2.0 ** (attempt - 1)))
                continue
            return False, str(exc)

        if response.status_code in {200, 204}:
            LOGGER.info("Discord webhook sent status=%s", response.status_code)
            return True, None

        if response.status_code == 429:
            retry_after = _discord_retry_after(response)
            LOGGER.warning("Discord webhook rate limited retry_after=%s body=%s", retry_after, response.text[:500])
            time.sleep(retry_after)
            continue

        error = f"Discord HTTP {response.status_code}: {response.text[:500]}"
        LOGGER.error(error)
        if response.status_code in {400, 401, 404}:
            return False, error
        if attempt < max_attempts:
            time.sleep(min(30.0, 2.0 ** (attempt - 1)))
            continue
        return False, error

    return False, "Discord webhook send exhausted retries"


def format_restock_detected(
    event: StockEvent,
    prediction: Prediction,
    prediction_id: int,
    *,
    include_airstrip: bool = True,
    include_business: bool = True,
) -> str:
    lines = [
        f"{event.country} Xanax Restock Detected",
        "",
        f"Observed at: {_format_ts_pair(event.observed_at)}",
        f"Normalized restock tick: {_format_ts_pair(event.normalized_at) if event.normalized_at else 'unknown'}",
        f"Quantity: {event.current_quantity}",
        "",
        f"Next predicted restock: {_format_ts_pair(prediction.predicted_restock_at)}",
        f"Prediction interval: {prediction.predicted_interval_ticks} ticks",
        f"Prediction ID: {prediction_id}",
    ]
    departure_lines: list[str] = []
    if include_airstrip:
        departure_lines.extend(
            [
                "Airstrip:",
                f"- Recommended departure: {_format_ts_pair(prediction.airstrip_recommended_departure_at)}",
                f"________________________________________________________________"
            ]
        )
    if include_business:
        if departure_lines:
            departure_lines.append("")
        departure_lines.extend(
            [
                "Business Class:",
                f"- Recommended departure: {_format_ts_pair(prediction.business_recommended_departure_at)}",
            ]
        )
    if departure_lines:
        lines.extend(["", "Recommended departures:", *departure_lines])
    return "\n".join(lines)


def format_airstrip_reminder(prediction: Prediction, ping_lead_minutes: int = 0, *, country: str | None = None) -> str:
    return "\n".join(
        [
            "Airstrip Departure Reminder",
            "",
            _restock_label(country),
            _format_ts_pair(prediction.effective_airstrip_target_restock_at),
            "",
            "Ping scheduled:",
            _format_ts_pair(prediction.airstrip_ping_at),
            "",
            _ping_explanation(ping_lead_minutes),
            "________________________________________________________________",
        ]
    )


def format_business_reminder(prediction: Prediction, ping_lead_minutes: int = 0, *, country: str | None = None) -> str:
    return "\n".join(
        [
            "Business Class Departure Reminder",
            "",
            _restock_label(country),
            _format_ts_pair(prediction.effective_business_class_target_restock_at),
            "",
            "Recommended Business Class departure:",
            _format_ts_pair(prediction.business_recommended_departure_at),
            "",
            _ping_explanation(ping_lead_minutes),
            "________________________________________________________________",
        ]
    )


def _format_ts_pair(dt: datetime) -> str:
    return f"{discord_ts(dt, 'F')} ({discord_ts(dt, 'R')})"


def _restock_label(country: str | None) -> str:
    if country:
        return f"Predicted {country} Xanax restock:"
    return "Predicted Xanax restock:"


def _ping_explanation(ping_lead_minutes: int) -> str:
    if ping_lead_minutes > 0:
        return (
            f"This ping is scheduled {ping_lead_minutes} minutes before recommended departure. "
        )
    return (
        "This ping is scheduled for the recommended departure time. "
    )


def _discord_retry_after(response: requests.Response) -> float:
    header = response.headers.get("Retry-After") or response.headers.get("X-RateLimit-Reset-After")
    if header:
        try:
            return max(0.0, float(header))
        except ValueError:
            pass
    try:
        body = response.json()
    except ValueError:
        return 5.0
    try:
        return max(0.0, float(body.get("retry_after", 5.0)))
    except (TypeError, ValueError, AttributeError):
        return 5.0
