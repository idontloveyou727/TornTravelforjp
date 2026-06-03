from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.models import StockObservation

LOGGER = logging.getLogger(__name__)

COUNTRY_CODE_ALIASES = {
    "uk": "uni",
    "united kingdom": "uni",
    "uni": "uni",
    "japan": "jap",
    "tokyo": "jap",
    "jpn": "jap",
    "jap": "jap",
}


class StockParseError(RuntimeError):
    pass


def extract_stock_observation(
    payload: dict[str, Any],
    *,
    item_id: int,
    country: str,
    country_aliases: tuple[str, ...],
    observed_at: datetime,
) -> StockObservation:
    stocks_root = payload.get("stocks")
    if not isinstance(stocks_root, dict):
        LOGGER.warning("Unexpected YATA payload shape: top-level keys=%s", sorted(payload.keys()))
        raise StockParseError("YATA payload is missing object field 'stocks'")

    country_key = _find_country_key(stocks_root, country, country_aliases)
    if country_key is None:
        LOGGER.warning(
            "Country not found in YATA payload country=%s aliases=%s available=%s",
            country,
            country_aliases,
            sorted(stocks_root.keys()),
        )
        raise StockParseError(f"Could not find country {country!r} in YATA payload")

    country_payload = stocks_root.get(country_key)
    if not isinstance(country_payload, dict):
        raise StockParseError(f"Country payload for {country_key!r} is not an object")

    stock_items = country_payload.get("stocks")
    if not isinstance(stock_items, list):
        raise StockParseError(f"Country payload for {country_key!r} is missing list field 'stocks'")

    for item in stock_items:
        if not isinstance(item, dict):
            continue
        if str(item.get("id")) == str(item_id):
            try:
                quantity = int(item["quantity"])
            except (KeyError, TypeError, ValueError) as exc:
                raise StockParseError(f"Item {item_id} has invalid quantity: {item!r}") from exc
            LOGGER.info("Parsed target stock country_key=%s item_id=%s quantity=%s", country_key, item_id, quantity)
            return StockObservation(
                observed_at=observed_at,
                item_id=item_id,
                country=country,
                quantity=quantity,
                raw_payload={"country_key": country_key, "country_payload": country_payload, "item": item},
            )

    LOGGER.warning(
        "Item not found in YATA country payload country_key=%s item_id=%s item_ids=%s",
        country_key,
        item_id,
        [item.get("id") for item in stock_items if isinstance(item, dict)],
    )
    raise StockParseError(f"Could not find item {item_id} for country {country!r}")


def _find_country_key(stocks_root: dict[str, Any], country: str, aliases: tuple[str, ...]) -> str | None:
    candidates = list(aliases) + [country]
    normalized_keys = {key.casefold(): key for key in stocks_root.keys()}

    for candidate in candidates:
        direct = normalized_keys.get(candidate.casefold())
        if direct:
            return direct
        mapped = COUNTRY_CODE_ALIASES.get(candidate.casefold())
        if mapped and mapped in stocks_root:
            return mapped
    return None

