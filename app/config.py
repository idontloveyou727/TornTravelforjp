from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


DEFAULT_YATA_URL = "https://yata.yt/api/v1/travel/export/"
UK_AIRSTRIP_DURATION_MINUTES = 111
UK_BUSINESS_CLASS_DURATION_MINUTES = 48
JAPAN_AIRSTRIP_DURATION_MINUTES = 158
JAPAN_BUSINESS_CLASS_DURATION_MINUTES = 68


def _get_env(name: str, fallback_name: str | None = None, default: str | None = None) -> str:
    value = os.getenv(name)
    if value is None and fallback_name:
        value = os.getenv(fallback_name)
    if value is None:
        if default is None:
            raise ValueError(f"Missing required environment variable: {name}")
        return default
    return value


def _parse_int(name: str, fallback_name: str | None, default: int, minimum: int = 1) -> int:
    raw = _get_env(name, fallback_name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")
    return value


def _parse_bool(name: str, fallback_name: str | None, default: bool) -> bool:
    raw = _get_env(name, fallback_name, "1" if default else "0").strip().casefold()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean-like value, got {raw!r}")


def _parse_aliases(country: str) -> tuple[str, ...]:
    raw = os.getenv("TARGET_COUNTRY_ALIASES", "")
    values = [part.strip() for part in raw.split(",") if part.strip()]
    values.append(country)
    if country.lower() in {"uk", "united kingdom"}:
        values.extend(["UK", "United Kingdom", "uni"])
    if country.lower() in {"japan", "tokyo", "jap", "jpn"}:
        values.extend(["Japan", "Tokyo", "jap", "jpn"])

    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            deduped.append(value)
    return tuple(deduped)


@dataclass(frozen=True)
class Config:
    yata_url: str
    item_id: int
    country: str
    country_aliases: tuple[str, ...]
    poll_seconds: int
    discord_webhook_url: str | None
    database_path: Path
    state_backend: str
    state_path: Path
    github_actions_delay_buffer_minutes: int
    ping_lead_minutes: int
    enable_airstrip_pings: bool
    enable_business_class_pings: bool
    airstrip_duration_minutes: int
    business_class_duration_minutes: int
    airstrip_target_restock_cycle: int
    business_class_target_restock_cycle: int
    default_depletion_rate_per_minute: float
    restock_backfill_rate_multiplier: float
    depletion_rate_history_window: int
    min_depletion_rate_sample_seconds: int
    depletion_rate_min_multiplier: float
    depletion_rate_max_multiplier: float
    prediction_interval_min_ticks: int
    prediction_interval_max_ticks: int
    prediction_interval_mad_threshold: float
    prediction_accuracy_tolerance_ticks: int
    prediction_accuracy_history_window: int
    prediction_history_window: int
    log_level: str

    def safe_summary(self) -> dict[str, object]:
        return {
            "yata_url": self.yata_url,
            "item_id": self.item_id,
            "country": self.country,
            "country_aliases": self.country_aliases,
            "poll_seconds": self.poll_seconds,
            "discord_webhook_enabled": bool(self.discord_webhook_url),
            "database_path": str(self.database_path),
            "state_backend": self.state_backend,
            "state_path": str(self.state_path),
            "github_actions_delay_buffer_minutes": self.github_actions_delay_buffer_minutes,
            "ping_lead_minutes": self.ping_lead_minutes,
            "enable_airstrip_pings": self.enable_airstrip_pings,
            "enable_business_class_pings": self.enable_business_class_pings,
            "airstrip_duration_minutes": self.airstrip_duration_minutes,
            "business_class_duration_minutes": self.business_class_duration_minutes,
            "airstrip_target_restock_cycle": self.airstrip_target_restock_cycle,
            "business_class_target_restock_cycle": self.business_class_target_restock_cycle,
            "default_depletion_rate_per_minute": self.default_depletion_rate_per_minute,
            "restock_backfill_rate_multiplier": self.restock_backfill_rate_multiplier,
            "depletion_rate_history_window": self.depletion_rate_history_window,
            "min_depletion_rate_sample_seconds": self.min_depletion_rate_sample_seconds,
            "depletion_rate_min_multiplier": self.depletion_rate_min_multiplier,
            "depletion_rate_max_multiplier": self.depletion_rate_max_multiplier,
            "prediction_interval_min_ticks": self.prediction_interval_min_ticks,
            "prediction_interval_max_ticks": self.prediction_interval_max_ticks,
            "prediction_interval_mad_threshold": self.prediction_interval_mad_threshold,
            "prediction_accuracy_tolerance_ticks": self.prediction_accuracy_tolerance_ticks,
            "prediction_accuracy_history_window": self.prediction_accuracy_history_window,
            "prediction_history_window": self.prediction_history_window,
            "log_level": self.log_level,
        }


def load_config() -> Config:
    env_file = os.getenv("ENV_FILE")
    if env_file:
        load_dotenv(env_file, override=True)
    else:
        load_dotenv()
    country = _get_env("COUNTRY", "TARGET_COUNTRY", "UK")
    webhook = os.getenv("DISCORD_WEBHOOK_URL") or None
    default_state_backend = "json" if os.getenv("GITHUB_ACTIONS", "").casefold() == "true" else "sqlite"
    depletion_rate_min_multiplier = _parse_float("DEPLETION_RATE_MIN_MULTIPLIER", None, 0.25, minimum=0.0001)
    depletion_rate_max_multiplier = _parse_float("DEPLETION_RATE_MAX_MULTIPLIER", None, 1.75, minimum=0.0001)
    if depletion_rate_max_multiplier < depletion_rate_min_multiplier:
        raise ValueError("DEPLETION_RATE_MAX_MULTIPLIER must be >= DEPLETION_RATE_MIN_MULTIPLIER")
    prediction_interval_min_ticks = _parse_int("PREDICTION_INTERVAL_MIN_TICKS", None, 80)
    prediction_interval_max_ticks = _parse_int("PREDICTION_INTERVAL_MAX_TICKS", None, 180)
    if prediction_interval_max_ticks < prediction_interval_min_ticks:
        raise ValueError("PREDICTION_INTERVAL_MAX_TICKS must be >= PREDICTION_INTERVAL_MIN_TICKS")
    return Config(
        yata_url=_get_env("YATA_URL", "YATA_TRAVEL_EXPORT_URL", DEFAULT_YATA_URL),
        item_id=_parse_int("ITEM_ID", "TARGET_ITEM_ID", 206),
        country=country,
        country_aliases=_parse_aliases(country),
        poll_seconds=_parse_int("POLL_SECONDS", "POLL_INTERVAL_SECONDS", 60),
        discord_webhook_url=webhook,
        database_path=Path(_get_env("DATABASE_PATH", None, "./data/restock_tracker.sqlite3")),
        state_backend=_get_env("STATE_BACKEND", None, default_state_backend).casefold(),
        state_path=Path(_get_env("STATE_PATH", None, "./data/github_actions_state.json")),
        github_actions_delay_buffer_minutes=_parse_int("GITHUB_ACTIONS_DELAY_BUFFER_MINUTES", None, 5, minimum=0),
        ping_lead_minutes=_parse_int("PING_LEAD_MINUTES", None, 0, minimum=0),
        enable_airstrip_pings=_parse_bool("ENABLE_AIRSTRIP", "ENABLE_AIRSTRIP_PINGS", True),
        enable_business_class_pings=_parse_bool("ENABLE_BUSINESS_CLASS", "ENABLE_BUSINESS_CLASS_PINGS", True),
        airstrip_duration_minutes=_parse_int(
            "AIRSTRIP_DURATION_MINUTES",
            None,
            _default_airstrip_duration_minutes(country),
        ),
        business_class_duration_minutes=_parse_int(
            "BUSINESS_CLASS_DURATION_MINUTES",
            None,
            _default_business_class_duration_minutes(country),
        ),
        airstrip_target_restock_cycle=_parse_int(
            "AIRSTRIP_TARGET_RESTOCK_CYCLE",
            None,
            _default_airstrip_target_restock_cycle(country),
        ),
        business_class_target_restock_cycle=_parse_int("BUSINESS_CLASS_TARGET_RESTOCK_CYCLE", None, 1),
        default_depletion_rate_per_minute=_parse_float("DEFAULT_DEPLETION_RATE_PER_MINUTE", None, 265, minimum=0.0001),
        restock_backfill_rate_multiplier=_parse_float("RESTOCK_BACKFILL_RATE_MULTIPLIER", None, 4, minimum=0.0001),
        depletion_rate_history_window=_parse_int("DEPLETION_RATE_HISTORY_WINDOW", None, 20),
        min_depletion_rate_sample_seconds=_parse_int("MIN_DEPLETION_RATE_SAMPLE_SECONDS", None, 90, minimum=0),
        depletion_rate_min_multiplier=depletion_rate_min_multiplier,
        depletion_rate_max_multiplier=depletion_rate_max_multiplier,
        prediction_interval_min_ticks=prediction_interval_min_ticks,
        prediction_interval_max_ticks=prediction_interval_max_ticks,
        prediction_interval_mad_threshold=_parse_float("PREDICTION_INTERVAL_MAD_THRESHOLD", None, 3.5, minimum=0),
        prediction_accuracy_tolerance_ticks=_parse_int("PREDICTION_ACCURACY_TOLERANCE_TICKS", None, 10, minimum=0),
        prediction_accuracy_history_window=_parse_int("PREDICTION_ACCURACY_HISTORY_WINDOW", None, 50),
        prediction_history_window=_parse_int("PREDICTION_HISTORY_WINDOW", None, 10),
        log_level=_get_env("LOG_LEVEL", None, "INFO").upper(),
    )


def _parse_float(name: str, fallback_name: str | None, default: float, minimum: float = 0.0) -> float:
    raw = _get_env(name, fallback_name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")
    return value


def _default_airstrip_duration_minutes(country: str) -> int:
    if country.casefold() in {"japan", "tokyo", "jap", "jpn"}:
        return JAPAN_AIRSTRIP_DURATION_MINUTES
    return UK_AIRSTRIP_DURATION_MINUTES


def _default_business_class_duration_minutes(country: str) -> int:
    if country.casefold() in {"japan", "tokyo", "jap", "jpn"}:
        return JAPAN_BUSINESS_CLASS_DURATION_MINUTES
    return UK_BUSINESS_CLASS_DURATION_MINUTES


def _default_airstrip_target_restock_cycle(country: str) -> int:
    if country.casefold() in {"japan", "tokyo", "jap", "jpn"}:
        return 2
    return 1
