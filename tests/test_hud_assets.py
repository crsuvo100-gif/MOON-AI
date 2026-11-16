from fastapi.testclient import TestClient

from app.terminal_interface import app


def test_hud_is_served():
    response = TestClient(app).get("/ui")

    assert response.status_code == 200
    assert "MOON-AI — NEURAL CORE" in response.text
    assert "fetch('/theme.json')" in response.text


def test_hud_theme_is_served_as_json():
    response = TestClient(app).get("/theme.json")

    assert response.status_code == 200
    assert response.json()["theme"] == "mono-red-black"
