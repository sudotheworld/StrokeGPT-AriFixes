from pathlib import Path

import pytest

from app import app, settings


@pytest.fixture(autouse=True)
def _isolate_settings(tmp_path, monkeypatch):
    """Ensure each test runs with an isolated settings file."""
    test_file = tmp_path / "settings.json"
    monkeypatch.setattr(settings, "file_path", Path(test_file))
    # Reset values to known defaults
    settings.auto_min_time = 4.0
    settings.auto_max_time = 7.0
    settings.milking_min_time = 2.5
    settings.milking_max_time = 4.5
    settings.edging_min_time = 5.0
    settings.edging_max_time = 8.0
    settings.save()
    yield


def test_mode_timings_update():
    client = app.test_client()
    payload = {
        "auto_min": 6.0,
        "auto_max": 9.5,
        "milking_min": 3.0,
        "milking_max": 6.0,
        "edging_min": 4.5,
        "edging_max": 7.5,
    }

    response = client.post("/api/mode_timings", json=payload)
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "success"
    assert data["timings"] == payload

    assert settings.auto_min_time == pytest.approx(payload["auto_min"])
    assert settings.auto_max_time == pytest.approx(payload["auto_max"])
    assert settings.milking_min_time == pytest.approx(payload["milking_min"])
    assert settings.milking_max_time == pytest.approx(payload["milking_max"])
    assert settings.edging_min_time == pytest.approx(payload["edging_min"])
    assert settings.edging_max_time == pytest.approx(payload["edging_max"])

