"""Regression: gateway router mounts and honours its configured auth gate."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.gateway as gateway_api
from app import terminal_interface


def test_gateway_router_is_mounted():
    paths = set(terminal_interface.app.openapi()["paths"])
    assert any("/gateway/health" in p for p in paths), "gateway routes missing from app"


def test_gateway_app_injects_real_token(monkeypatch):
    # terminal_interface must push its configured token into the gateway module
    # when it builds the app; otherwise the gateway routes would be unguarded.
    assert gateway_api.TERMINAL_TOKEN == terminal_interface.TERMINAL_TOKEN


def test_gateway_auth_binds_configured_token(monkeypatch):
    monkeypatch.setattr(gateway_api, "TERMINAL_TOKEN", "SECRET_TOKEN")
    monkeypatch.setattr(
        gateway_api,
        "_token_ok",
        lambda headers: headers.get("authorization") == "Bearer SECRET_TOKEN",
    )
    app = FastAPI()
    app.include_router(gateway_api.get_gateway_router())
    client = TestClient(app)
    path = "/gateway/health"
    assert client.get(path).status_code == 401
    ok = client.get(path, headers={"Authorization": "Bearer SECRET_TOKEN"})
    assert ok.status_code == 200
