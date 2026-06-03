from datetime import datetime, timedelta, timezone

from app.predictor import METHOD_DEFAULT, METHOD_MEDIAN, filter_prediction_intervals, predict_next_restock
from app.tick import is_aligned_to_1_minute_tick


def dt(hour: int, minute: int) -> datetime:
    return datetime(2026, 5, 18, hour, minute, tzinfo=timezone.utc)


def test_default_prediction_when_history_has_fewer_than_three_intervals() -> None:
    prediction = predict_next_restock(
        current_restock_event_id=1,
        current_normalized_restock_at=dt(8, 5),
        historical_restock_times=[dt(8, 5)],
        history_window=10,
        departure_buffer_minutes=5,
        ping_lead_minutes=0,
    )

    assert prediction.predicted_restock_at == dt(10, 10)
    assert prediction.predicted_interval_ticks == 125
    assert prediction.prediction_method == METHOD_DEFAULT


def test_median_prediction() -> None:
    intervals = [120, 125, 125, 126, 130]
    start = dt(0, 0)
    restocks = [start]
    for ticks in intervals:
        restocks.append(restocks[-1] + timedelta(minutes=ticks))

    prediction = predict_next_restock(
        current_restock_event_id=1,
        current_normalized_restock_at=restocks[-1],
        historical_restock_times=restocks,
        history_window=10,
        departure_buffer_minutes=5,
        ping_lead_minutes=0,
    )

    assert prediction.predicted_interval_ticks == 125
    assert prediction.prediction_method == METHOD_MEDIAN
    assert prediction.predicted_restock_at == restocks[-1] + timedelta(minutes=125)
    assert is_aligned_to_1_minute_tick(prediction.predicted_restock_at)


def test_prediction_filters_outlier_intervals_before_median() -> None:
    prediction = predict_next_restock(
        current_restock_event_id=1,
        current_normalized_restock_at=dt(8, 5),
        historical_restock_times=[],
        historical_interval_ticks=[113, 114, 108, 115, 128, 236, 123, 360, 117, 115],
        history_window=10,
    )

    assert prediction.predicted_interval_ticks == 115
    assert prediction.prediction_method == METHOD_MEDIAN


def test_prediction_falls_back_when_filtered_history_is_too_small() -> None:
    prediction = predict_next_restock(
        current_restock_event_id=1,
        current_normalized_restock_at=dt(8, 5),
        historical_restock_times=[],
        historical_interval_ticks=[50, 60, 236, 360],
        history_window=10,
    )

    assert prediction.predicted_interval_ticks == 125
    assert prediction.prediction_method == METHOD_DEFAULT


def test_prediction_interval_bounds_apply_before_mad_filtering() -> None:
    assert filter_prediction_intervals([70, 100, 110, 120, 130, 190]) == [100, 110, 120, 130]
