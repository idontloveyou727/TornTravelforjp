from datetime import datetime, timezone

from app.predictor import METHOD_DEFAULT, build_prediction


def test_departure_and_ping_times() -> None:
    prediction = build_prediction(
        event_id=1,
        predicted_restock_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        interval_ticks=25,
        method=METHOD_DEFAULT,
        departure_buffer_minutes=5,
        ping_lead_minutes=0,
    )

    assert prediction.airstrip_latest_departure_at == datetime(2026, 1, 1, 10, 9, tzinfo=timezone.utc)
    assert prediction.airstrip_recommended_departure_at == datetime(2026, 1, 1, 10, 4, tzinfo=timezone.utc)
    assert prediction.airstrip_ping_at == datetime(2026, 1, 1, 10, 4, tzinfo=timezone.utc)
    assert prediction.business_latest_departure_at == datetime(2026, 1, 1, 11, 12, tzinfo=timezone.utc)
    assert prediction.business_recommended_departure_at == datetime(2026, 1, 1, 11, 7, tzinfo=timezone.utc)
    assert prediction.business_ping_at == datetime(2026, 1, 1, 11, 7, tzinfo=timezone.utc)


def test_departure_with_larger_buffer_and_ping_lead() -> None:
    prediction = build_prediction(
        event_id=1,
        predicted_restock_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        interval_ticks=25,
        method=METHOD_DEFAULT,
        departure_buffer_minutes=10,
        ping_lead_minutes=5,
    )

    assert prediction.airstrip_latest_departure_at == datetime(2026, 1, 1, 10, 9, tzinfo=timezone.utc)
    assert prediction.airstrip_recommended_departure_at == datetime(2026, 1, 1, 9, 59, tzinfo=timezone.utc)
    assert prediction.airstrip_ping_at == datetime(2026, 1, 1, 9, 54, tzinfo=timezone.utc)
    assert prediction.business_latest_departure_at == datetime(2026, 1, 1, 11, 12, tzinfo=timezone.utc)
    assert prediction.business_recommended_departure_at == datetime(2026, 1, 1, 11, 2, tzinfo=timezone.utc)
    assert prediction.business_ping_at == datetime(2026, 1, 1, 10, 57, tzinfo=timezone.utc)


def test_japan_airstrip_targets_second_restock_while_business_targets_first() -> None:
    prediction = build_prediction(
        event_id=1,
        predicted_restock_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        interval_ticks=125,
        method=METHOD_DEFAULT,
        departure_buffer_minutes=5,
        ping_lead_minutes=0,
        airstrip_duration_minutes=158,
        business_class_duration_minutes=68,
        airstrip_target_restock_cycle=2,
        business_class_target_restock_cycle=1,
        projected_depletion_rate_per_minute=250,
    )

    assert prediction.predicted_restock_at == datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert prediction.effective_airstrip_target_restock_at == datetime(2026, 1, 1, 14, 15, tzinfo=timezone.utc)
    assert prediction.effective_business_class_target_restock_at == datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert prediction.airstrip_latest_departure_at == datetime(2026, 1, 1, 11, 37, tzinfo=timezone.utc)
    assert prediction.airstrip_recommended_departure_at == datetime(2026, 1, 1, 11, 32, tzinfo=timezone.utc)
    assert prediction.business_latest_departure_at == datetime(2026, 1, 1, 10, 52, tzinfo=timezone.utc)
    assert prediction.business_recommended_departure_at == datetime(2026, 1, 1, 10, 47, tzinfo=timezone.utc)
