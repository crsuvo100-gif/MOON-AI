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


def test_api_disconnect_requires_authenticated_operator_confirmation(
    monkeypatch, tmp_path
):
    client, gateway = _client(monkeypatch, tmp_path)
    gateway.register(ConnectionRecord(
        name="saved-agent",
        kind="agent",
        url="https://agent.example/v1",
        scope="network.agent",
    ))
    token = "operator-test-token"
    monkeypatch.setattr(gateway_api, "TERMINAL_TOKEN", token)
    monkeypatch.setattr(
        gateway_api,
        "_token_ok",
        lambda headers: headers.get("authorization") == f"Bearer {token}",
    )
    auth_headers = {"Authorization": f"Bearer {token}"}

    denied = client.request("DELETE", "/gateway/connections/saved-agent")
    assert denied.status_code == 401
    assert gateway.get("saved-agent") is not None

    unconfirmed = client.request(
        "DELETE",
        "/gateway/connections/saved-agent",
        json={},
        headers=auth_headers,
    )
    assert unconfirmed.status_code == 403
    assert gateway.get("saved-agent") is not None

    approved = client.request(
        "DELETE",
        "/gateway/connections/saved-agent",
        json={"confirmed": True},
        headers=auth_headers,
    )
    assert approved.status_code == 200
    assert gateway.get("saved-agent") is None


def test_api_rejects_invalid_agent_manifest_and_preserves_registry(
    monkeypatch, tmp_path
):
    client, gateway = _client(monkeypatch, tmp_path)
    payload = {
        "name": "invalid-agent",
        "kind": "agent",
        "url": "https://agent.example/v1",
        "manifest": {"schema_version": 999},
    }

    response = client.post("/gateway/connections", json=payload)

    assert response.status_code == 400
    assert "unsupported agent manifest" in response.json()["error"]
    assert gateway.get("invalid-agent") is None


def test_api_accepts_and_returns_valid_agent_manifest(monkeypatch, tmp_path):
    client, gateway = _client(monkeypatch, tmp_path)
    monkeypatch.setenv("ALLOWED_EGRESS_HOSTS", "agent.example")
    manifest = {
        "schema_version": 1,
        "agent_id": "research-agent",
        "name": "Research Agent",
        "version": "1.0",
        "protocol": "openai-chat-completions",
        "capabilities": [
            {
                "name": "summarize",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
            }
        ],
    }

    created = client.post(
        "/gateway/connections",
        json={
            "name": "research-agent",
            "kind": "agent",
            "url": "https://agent.example/v1",
            "manifest": manifest,
        },
    )
    inspected = client.get("/gateway/connections/research-agent")

    assert created.status_code == 201
    assert inspected.status_code == 200
    persisted_manifest = gateway.get("research-agent").manifest
    assert inspected.json()["manifest"] == persisted_manifest
    assert persisted_manifest["capabilities"][0]["input_schema"] == {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }


@pytest.mark.asyncio
async def test_api_manifest_discovery_requires_token_authenticated_confirmation(
    monkeypatch, tmp_path
):
    client, gateway = _client(monkeypatch, tmp_path)
    gateway.register(ConnectionRecord(
        name="remote-agent",
        kind="agent",
        url="https://agent.example/v1",
        scope="network.agent",
    ))
    seen_confirmation = []

    async def fake_discover(name, *, confirmed=False):
        seen_confirmation.append(confirmed)
        if not confirmed:
            return {"ok": False, "confirmation_required": True, "error": "approval required"}
        return {"ok": True, "name": name, "manifest": {"schema_version": 1}}

    monkeypatch.setattr(gateway, "discover_agent_manifest", fake_discover)

    denied = client.post(
        "/gateway/connections/remote-agent/discover",
        json={"confirmed": True},
    )
    assert denied.status_code == 403
    assert seen_confirmation == [False]

    token = "operator-test-token"
    monkeypatch.setattr(gateway_api, "TERMINAL_TOKEN", token)
    monkeypatch.setattr(
        gateway_api,
        "_token_ok",
        lambda headers: headers.get("authorization") == f"Bearer {token}",
    )
    approved = client.post(
        "/gateway/connections/remote-agent/discover",
        json={"confirmed": True},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert approved.status_code == 200
    assert seen_confirmation == [False, True]


def test_api_agent_task_submit_and_status_require_configured_authentication(
    monkeypatch, tmp_path
):
    client, gateway = _client(monkeypatch, tmp_path)
    gateway.register(ConnectionRecord(
        name="remote-agent",
        kind="agent",
        url="https://agent.example/v1",
        scope="network.agent",
    ))
    token = "operator-test-token"
    monkeypatch.setattr(gateway_api, "TERMINAL_TOKEN", token)
    monkeypatch.setattr(
        gateway_api,
        "_token_ok",
        lambda headers: headers.get("authorization") == f"Bearer {token}",
    )
    seen_confirmation = []

    async def fake_submit(
        name, message, *, system="", confirmed=False, capability="", input_data=None
    ):
        seen_confirmation.append(confirmed)
        if not confirmed:
            return {"ok": False, "confirmation_required": True, "error": "approval required"}
        return {
            "ok": True,
            "task_id": "task-123",
            "connection_name": name,
            "status": "queued",
        }

    monkeypatch.setattr(gateway, "submit_agent_task", fake_submit)
    unauthenticated = client.post(
        "/gateway/connections/remote-agent/tasks",
        json={"message": "delegate", "confirmed": True},
    )
    assert unauthenticated.status_code == 401

    headers = {"Authorization": f"Bearer {token}"}
    denied = client.post(
        "/gateway/connections/remote-agent/tasks",
        json={"message": "delegate", "confirmed": False},
        headers=headers,
    )
    assert denied.status_code == 403
    assert seen_confirmation == [False]

    submitted = client.post(
        "/gateway/connections/remote-agent/tasks",
        json={"message": "delegate", "confirmed": True},
        headers=headers,
    )
    assert submitted.status_code == 202
    assert submitted.json()["task_id"] == "task-123"
    assert seen_confirmation == [False, True]

    monkeypatch.setattr(
        gateway,
        "get_agent_task",
        lambda task_id: {"task_id": task_id, "status": "completed", "answer": "done"},
    )
    assert client.get("/gateway/tasks/task-123").status_code == 401
    status = client.get("/gateway/tasks/task-123", headers=headers)
    assert status.status_code == 200
    assert status.json()["answer"] == "done"


@pytest.mark.asyncio
async def test_api_agent_task_executes_and_persists_result(monkeypatch, tmp_path):
    import asyncio

    import httpx

    from app.connector.connectors import CallResult

    monkeypatch.setenv("ALLOWED_EGRESS_HOSTS", "agent.example")
    gateway = ConnectionGateway(root=tmp_path)
    gateway.register(ConnectionRecord(
        name="agent",
        kind="agent",
        url="https://agent.example/v1",
        scope="network.agent",
        manifest={
            "schema_version": 1,
            "agent_id": "structured-peer",
            "name": "Structured Peer",
            "version": "1.0",
            "protocol": "openai-chat-completions",
            "capabilities": [{
                "name": "summarize",
                "input_schema": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                    "additionalProperties": False,
                },
                "output_schema": {
                    "type": "object",
                    "properties": {"summary": {"type": "string"}},
                    "required": ["summary"],
                    "additionalProperties": False,
                },
            }],
        },
    ))
    monkeypatch.setattr(gateway_api, "_gateway", gateway)
    monkeypatch.setattr(gateway_api, "TERMINAL_TOKEN", "")

    class FakeAgent:
        async def ask(self, message, *, system="", history=None):
            assert "source text" in message
            return CallResult(
                ok=True, status=200, data={"answer": '{"summary":"api task result"}'}
            )

    monkeypatch.setattr(gateway, "build_connector", lambda _record: FakeAgent())
    app = FastAPI()
    app.include_router(gateway_api.get_gateway_router())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        submitted = await client.post(
            "/gateway/connections/agent/tasks",
            json={
                "capability": "summarize",
                "input": {"text": "source text"},
            },
        )
        assert submitted.status_code == 202
        task_id = submitted.json()["task_id"]
        for _ in range(100):
            status = await client.get(f"/gateway/tasks/{task_id}")
            if status.json()["status"] in {"completed", "failed", "interrupted"}:
                break
            await asyncio.sleep(0.01)

    assert status.json()["status"] == "completed"
    assert status.json()["answer"] == '{"summary":"api task result"}'
    assert "source text" not in gateway._task_file.read_text(encoding="utf-8")


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
