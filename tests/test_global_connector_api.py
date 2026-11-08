import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.gateway as gateway_api
from app.connector.gateway import ConnectionGateway, ConnectionRecord
from app.connector.hub import IntegrationHub


def _client(monkeypatch, tmp_path):
    gateway = ConnectionGateway(root=tmp_path)
    monkeypatch.setattr(gateway_api, "_gateway", gateway)
    monkeypatch.setattr(gateway_api, "TERMINAL_TOKEN", "")
    app = FastAPI()
    app.include_router(gateway_api.get_gateway_router())
    return TestClient(app), gateway


def test_api_connection_registration_requires_remote_egress_confirmation(
    monkeypatch, tmp_path
):
    client, gateway = _client(monkeypatch, tmp_path)
    token = "operator-test-token"
    monkeypatch.setattr(gateway_api, "TERMINAL_TOKEN", token)
    monkeypatch.setattr(
        gateway_api,
        "_token_ok",
        lambda headers: headers.get("authorization") == f"Bearer {token}",
    )
    payload = {
        "name": "remote-agent",
        "kind": "agent",
        "url": "https://agent.example/v1",
        "scope": "network.agent",
    }

    auth_headers = {"Authorization": f"Bearer {token}"}
    denied = client.post(
        "/gateway/connections", json=payload, headers=auth_headers
    )

    assert denied.status_code == 403
    assert denied.json()["confirmation_required"] is True
    assert gateway.get("remote-agent") is None

    unauthenticated = client.post(
        "/gateway/connections", json={**payload, "confirmed": True}
    )
    assert unauthenticated.status_code == 401

    approved = client.post(
        "/gateway/connections",
        json={**payload, "confirmed": True},
        headers=auth_headers,
    )

    assert approved.status_code == 201
    assert gateway.get("remote-agent") is not None


def test_api_health_check_requires_confirmation_before_network_probe(
    monkeypatch, tmp_path
):
    client, gateway = _client(monkeypatch, tmp_path)
    gateway.register(ConnectionRecord(
        name="remote-agent",
        kind="agent",
        url="https://agent.example/v1",
        scope="network.agent",
    ))

    def unexpected_probe(_record):
        raise AssertionError("an unconfirmed remote probe must not run")

    monkeypatch.setattr(gateway, "build_connector", unexpected_probe)

    response = client.post("/gateway/connections/remote-agent/check", json={})

    assert response.status_code == 403
    assert response.json()["confirmation_required"] is True


@pytest.mark.asyncio
async def test_integration_hub_health_gates_remote_probes(monkeypatch, tmp_path):
    hub = IntegrationHub(
        capability_root=tmp_path / "capabilities",
        connections_root=tmp_path / "connections",
    )
    hub.connection_gateway.register(ConnectionRecord(
        name="remote-agent",
        kind="agent",
        url="https://agent.example/v1",
        scope="network.agent",
    ))

    def unexpected_probe(_record):
        raise AssertionError("an unconfirmed remote probe must not run")

    monkeypatch.setattr(hub.connection_gateway, "build_connector", unexpected_probe)

    result = await hub.health()

    assert result["items"][0]["status"] == "CONFIRMATION_REQUIRED"
