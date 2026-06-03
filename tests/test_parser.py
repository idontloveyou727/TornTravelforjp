from datetime import datetime, timezone

from app.parser import extract_stock_observation


def test_extracts_uk_item_206_from_yata_shape() -> None:
    payload = {
        "stocks": {
            "uni": {
                "update": 1779102633,
                "stocks": [
                    {"id": 205, "name": "Vicodin", "quantity": 48, "cost": 1723},
                    {"id": "206", "name": "Xanax", "quantity": "7", "cost": 722531},
                ],
            }
        },
        "timestamp": 1779102711,
    }

    observation = extract_stock_observation(
        payload,
        item_id=206,
        country="UK",
        country_aliases=("UK", "United Kingdom"),
        observed_at=datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc),
    )

    assert observation.quantity == 7
    assert observation.raw_payload is not None
    assert observation.raw_payload["country_key"] == "uni"


def test_extracts_japan_item_206_from_aliases() -> None:
    payload = {
        "stocks": {
            "jap": {
                "stocks": [
                    {"id": 206, "name": "Xanax", "quantity": "42", "cost": 1},
                ],
            }
        }
    }

    observation = extract_stock_observation(
        payload,
        item_id=206,
        country="Japan",
        country_aliases=("Japan", "Tokyo", "jpn"),
        observed_at=datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc),
    )

    assert observation.country == "Japan"
    assert observation.quantity == 42
    assert observation.raw_payload is not None
    assert observation.raw_payload["country_key"] == "jap"
