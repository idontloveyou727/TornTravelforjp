from datetime import datetime, timezone

from app.depletion import (
    DEFAULT_DEPLETION_RATE_PER_MINUTE,
    HIGH_TRAFFIC,
    LOW_TRAFFIC,
    MID_TRAFFIC,
    calculate_exact_restock_time,
    calculate_depletion_rate_per_minute,
    depletion_bucket_for_tct_time,
    estimate_depleted_time_from_last_positive,
    estimate_restock_time_from_observation,
    filter_depletion_rate_history,
    normalize_depletion_rate_history,
    stable_depletion_rate,
)
from app.models import StockObservation


def obs(hour: int, minute: int, second: int, quantity: int) -> StockObservation:
    return StockObservation(
        observed_at=datetime(2026, 1, 1, hour, minute, second, tzinfo=timezone.utc),
        item_id=206,
        country="UK",
        quantity=quantity,
    )


def test_depletion_rate_uses_only_positive_to_positive_drop() -> None:
    assert calculate_depletion_rate_per_minute(obs(0, 0, 0, 1982), obs(0, 2, 0, 1562)) == 210
    assert calculate_depletion_rate_per_minute(obs(0, 0, 0, 0), obs(0, 2, 0, 1772)) is None
    assert calculate_depletion_rate_per_minute(obs(0, 0, 0, 19), obs(0, 2, 0, 0)) is None
    assert calculate_depletion_rate_per_minute(obs(0, 0, 0, 100), obs(0, 2, 0, 150)) is None


def test_depletion_rate_ignores_too_short_samples() -> None:
    assert calculate_depletion_rate_per_minute(obs(0, 0, 0, 1982), obs(0, 1, 0, 1772)) is None


def test_depletion_bucket_for_tct_time_boundaries() -> None:
    assert depletion_bucket_for_tct_time(obs(0, 0, 0, 1).observed_at) == LOW_TRAFFIC
    assert depletion_bucket_for_tct_time(obs(7, 59, 0, 1).observed_at) == LOW_TRAFFIC
    assert depletion_bucket_for_tct_time(obs(8, 0, 0, 1).observed_at) == MID_TRAFFIC
    assert depletion_bucket_for_tct_time(obs(15, 59, 0, 1).observed_at) == MID_TRAFFIC
    assert depletion_bucket_for_tct_time(obs(16, 0, 0, 1).observed_at) == HIGH_TRAFFIC
    assert depletion_bucket_for_tct_time(obs(23, 59, 0, 1).observed_at) == HIGH_TRAFFIC


def test_normalize_depletion_rate_history_resets_legacy_flat_history() -> None:
    assert normalize_depletion_rate_history([250, 260]) == {
        LOW_TRAFFIC: [],
        MID_TRAFFIC: [],
        HIGH_TRAFFIC: [],
    }


def test_stable_depletion_rate_uses_default_during_cold_start() -> None:
    assert stable_depletion_rate([], default_rate=265) == DEFAULT_DEPLETION_RATE_PER_MINUTE
    assert stable_depletion_rate([250], default_rate=265) == DEFAULT_DEPLETION_RATE_PER_MINUTE
    assert stable_depletion_rate([250, 260], default_rate=265) == DEFAULT_DEPLETION_RATE_PER_MINUTE


def test_stable_depletion_rate_uses_filtered_median_after_cold_start() -> None:
    assert stable_depletion_rate([250, 260, 270], default_rate=265) == 260


def test_calculate_exact_restock_time_uses_observed_quantity_and_drpm() -> None:
    observed_at = datetime(2026, 1, 1, 12, 7, 12, tzinfo=timezone.utc)

    assert calculate_exact_restock_time(observed_at, current_quantity=2100, drpm=200) == datetime(
        2026, 1, 1, 12, 5, tzinfo=timezone.utc
    )


def test_calculate_exact_restock_time_returns_observed_minute_for_full_stock() -> None:
    observed_at = datetime(2026, 1, 1, 12, 7, 59, tzinfo=timezone.utc)

    assert calculate_exact_restock_time(observed_at, current_quantity=2500, drpm=200) == datetime(
        2026, 1, 1, 12, 7, tzinfo=timezone.utc
    )


def test_calculate_exact_restock_time_uses_default_drpm_when_invalid() -> None:
    observed_at = datetime(2026, 1, 1, 12, 7, 59, tzinfo=timezone.utc)

    assert calculate_exact_restock_time(observed_at, current_quantity=1970, drpm=0) == datetime(
        2026, 1, 1, 12, 5, tzinfo=timezone.utc
    )


def test_restock_estimate_wrapper_uses_exact_restock_time() -> None:
    assert estimate_restock_time_from_observation(obs(12, 7, 12, 2100), rate_per_minute=200) == datetime(
        2026, 1, 1, 12, 5, tzinfo=timezone.utc
    )


def test_estimated_depleted_at_ceil_to_next_minute() -> None:
    estimate = estimate_depleted_time_from_last_positive(obs(0, 20, 2, 5), rate_per_minute=265)

    assert estimate.estimated_at == datetime(2026, 1, 1, 0, 21, 0, tzinfo=timezone.utc)


def test_filter_depletion_rate_history_removes_obvious_bounds_outliers() -> None:
    history = [250, 251, 252, 40, 900, 253, 254]

    assert filter_depletion_rate_history(history, default_rate=250) == [250, 251, 252, 253, 254]
    assert stable_depletion_rate(history, default_rate=250) == 252


def test_filter_depletion_rate_history_removes_mad_outliers() -> None:
    history = [
        245.76982283829486,
        242.3361936072318,
        78.45579383778774,
        386.575588865477,
        459.9477191334383,
        268.76836797640857,
        260.0914330146905,
        265.3097740920848,
    ]

    filtered = filter_depletion_rate_history(history, default_rate=265)

    assert 78.45579383778774 not in filtered
    assert 386.575588865477 not in filtered
    assert 459.9477191334383 not in filtered
    assert filtered == [
        245.76982283829486,
        242.3361936072318,
        268.76836797640857,
        260.0914330146905,
        265.3097740920848,
    ]
