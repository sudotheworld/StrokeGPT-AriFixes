from pathlib import Path


def test_generate_and_store_theme_preset(monkeypatch, tmp_path):
    from app import app, settings, llm

    # Point settings at an isolated file so tests don't mutate real settings.
    original_path = settings.file_path
    settings.file_path = Path(tmp_path) / "settings.json"
    settings.theme_presets = []
    settings.save()

    def fake_theme(existing_names=None):
        return {
            "theme_name": "Test Aurora",
            "background": "#101018",
            "glass": "rgba(16,18,24,0.6)",
            "glass_strong": "rgba(18,20,28,0.85)",
            "text": "#f5f7ff",
            "muted": "#8890a0",
            "edge": "rgba(255,0,160,0.35)",
            "brand_colors": ["#ff00a0", "#00ffff", "#20ffb5", "#ffd166", "#c4a5ff"],
            "ok": "#23d18b",
            "warn": "#ffb454",
            "bad": "#ff3b6b",
        }

    monkeypatch.setattr(llm, "generate_theme_palette", fake_theme)

    client = app.test_client()

    resp = client.post('/api/themes/generate')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    preset = data["preset"]
    assert preset["name"] == "Test Aurora"
    assert preset["colors"]["background"] == "#101018"
    assert len(settings.theme_presets) == 1

    preset_id = preset["id"]
    screenshot_payload = {"image": "data:image/png;base64,AAAA"}
    resp2 = client.post(f'/api/themes/{preset_id}/screenshot', json=screenshot_payload)
    assert resp2.status_code == 200
    assert settings.theme_presets[0]["screenshot"] == "data:image/png;base64,AAAA"

    resp3 = client.get('/api/themes')
    assert resp3.status_code == 200
    listed = resp3.get_json()["presets"]
    assert any(p["id"] == preset_id for p in listed)

    # Restore original settings file
    settings.file_path = original_path
    settings.load()
