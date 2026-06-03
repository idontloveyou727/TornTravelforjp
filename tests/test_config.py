from app.config import load_config


def test_prediction_config_defaults(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    for name in [
        "PREDICTION_INTERVAL_MIN_TICKS",
        "PREDICTION_INTERVAL_MAX_TICKS",
        "PREDICTION_INTERVAL_MAD_THRESHOLD",
        "PREDICTION_ACCURACY_TOLERANCE_TICKS",
        "PREDICTION_ACCURACY_HISTORY_WINDOW",
    ]:
        monkeypatch.delenv(name, raising=False)

    config = load_config()

    assert config.prediction_interval_min_ticks == 80
    assert config.prediction_interval_max_ticks == 180
    assert config.prediction_interval_mad_threshold == 3.5
    assert config.prediction_accuracy_tolerance_ticks == 10
    assert config.prediction_accuracy_history_window == 50
    assert config.airstrip_duration_minutes == 111
    assert config.business_class_duration_minutes == 48
    assert config.airstrip_target_restock_cycle == 1
    assert config.business_class_target_restock_cycle == 1


def test_prediction_interval_max_must_be_greater_than_min(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PREDICTION_INTERVAL_MIN_TICKS", "180")
    monkeypatch.setenv("PREDICTION_INTERVAL_MAX_TICKS", "80")

    try:
        load_config()
    except ValueError as exc:
        assert "PREDICTION_INTERVAL_MAX_TICKS must be >= PREDICTION_INTERVAL_MIN_TICKS" in str(exc)
    else:
        raise AssertionError("Expected invalid prediction interval bounds to fail")


def test_env_file_loads_japan_defaults(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / ".env.jp"
    env_file.write_text(
        "\n".join(
            [
                "COUNTRY=Japan",
                "TARGET_COUNTRY_ALIASES=Japan,Tokyo,jap,jpn",
                "STATE_PATH=./data/github_actions_state_jp.json",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENV_FILE", str(env_file))

    config = load_config()

    assert config.country == "Japan"
    assert config.country_aliases == ("Japan", "Tokyo", "jap", "jpn")
    assert config.state_path.as_posix() == "data/github_actions_state_jp.json"
    assert config.airstrip_duration_minutes == 158
    assert config.business_class_duration_minutes == 68
    assert config.airstrip_target_restock_cycle == 2
    assert config.business_class_target_restock_cycle == 1
