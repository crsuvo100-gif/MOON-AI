import json

import pytest

import app.connector.gateway as gateway_module
from app.brain.tool_manager import ToolManager
from app.connector.gateway import ConnectionGateway, ConnectionRecord
from app.connector.manifest import (
    MANIFEST_SCHEMA_VERSION,
    MAX_MANIFEST_BYTES,
    ManifestValidationError,
    validate_agent_manifest,
    validate_capability_payload,
)
from app.connector.tool import GlobalConnectorTool


def _manifest():
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "agent_id": "research-agent",
        "name": "Research Agent",
        "version": "1.2.0",
        "protocol": "openai-chat-completions",
        "capabilities": [
            {
                "name": "summarize",
                "description": "Summarize a document.",
                "input_schema": {
                    "type": "object",
                    "properties": {"text": {"type": "string", "maxLength": 1000}},
                    "required": ["text"],
                    "additionalProperties": False,
                },
                "output_schema": {
                    "type": "object",
                    "properties": {"summary": {"type": "string"}},
                    "required": ["summary"],
                    "additionalProperties": False,
                },
            }
        ],
    }


def test_agent_manifest_validates_and_normalizes():
    manifest = _manifest()

    assert validate_agent_manifest(manifest) == manifest


@pytest.mark.parametrize(
    ("schema", "value"),
    [
        (_manifest()["capabilities"][0]["input_schema"], {"text": "source"}),
        (_manifest()["capabilities"][0]["output_schema"], {"summary": "result"}),
        ({"type": "object", "properties": {"n": {"type": "integer", "minimum": 2}}}, {"n": 2}),
    ],
)
def test_capability_payload_accepts_values_matching_declared_schema(schema, value):
    validate_capability_payload(schema, value)


@pytest.mark.parametrize(
    ("schema", "value", "message"),
    [
        (_manifest()["capabilities"][0]["input_schema"], {"text": 12}, "type string"),
        (_manifest()["capabilities"][0]["input_schema"], {"text": "x", "extra": 1}, "unsupported"),
        (_manifest()["capabilities"][0]["input_schema"], {}, "missing required"),
        (
            {"type": "object", "properties": {"n": {"type": "integer"}}},
            {"n": True},
            "type integer",
        ),
        (
            {"type": "object", "properties": {"flag": {"type": "boolean", "enum": [1]}}},
            {"flag": True},
            "enum",
        ),
    ],
)
def test_capability_payload_rejects_values_outside_declared_schema(schema, value, message):
    with pytest.raises(ManifestValidationError, match=message):
        validate_capability_payload(schema, value)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"schema_version": 2}, "unsupported agent manifest"),
        ({"schema_version": True}, "unsupported agent manifest"),
        ({"protocol": "unknown"}, "unsupported agent protocol"),
        ({"permissions": ["network.admin"]}, "unsupported fields"),
        ({"agent_id": "../other"}, "simple identifier"),
    ],
)
def test_agent_manifest_rejects_incompatible_or_unsafe_fields(change, message):
    manifest = {**_manifest(), **change}

    with pytest.raises(ManifestValidationError, match=message):
        validate_agent_manifest(manifest)


def test_agent_manifest_rejects_duplicate_capabilities_and_invalid_schemas():
    manifest = _manifest()
    manifest["capabilities"].append(manifest["capabilities"][0])

    with pytest.raises(ManifestValidationError, match="unique"):
        validate_agent_manifest(manifest)

    manifest = _manifest()
    manifest["capabilities"][0]["input_schema"] = {
        "type": "object",
        "required": ["missing"],
    }
    with pytest.raises(ManifestValidationError, match="required"):
        validate_agent_manifest(manifest)

    manifest = _manifest()
    manifest["capabilities"][0]["input_schema"] = {"type": []}
    with pytest.raises(ManifestValidationError, match="schema root"):
        validate_agent_manifest(manifest)


def test_agent_manifest_rejects_oversized_input_before_normalization():
    manifest = _manifest()
    manifest["description"] = "x" * 33_000

    with pytest.raises(ManifestValidationError, match="32768-byte"):
        validate_agent_manifest(manifest)


def test_gateway_persists_manifest_and_keeps_legacy_records_compatible(tmp_path):
    gateway = ConnectionGateway(root=tmp_path)
    record = ConnectionRecord(
        name="research-agent",
        kind="agent",
        url="https://agent.example/v1",
        manifest=_manifest(),
    )
    gateway.register(record)

    persisted = json.loads(gateway._file.read_text(encoding="utf-8"))
    assert persisted[0]["manifest"] == _manifest()
    assert ConnectionGateway(root=tmp_path).get("research-agent").manifest == _manifest()

    legacy = ConnectionRecord(name="legacy", kind="agent", url="https://legacy.example/v1")
    gateway.register(legacy)
    assert ConnectionGateway(root=tmp_path).get("legacy").manifest is None


def test_gateway_rejects_invalid_manifest_without_replacing_saved_record(tmp_path):
    gateway = ConnectionGateway(root=tmp_path)
    gateway.register(ConnectionRecord(
        name="existing",
        kind="agent",
        url="https://agent.example/v1",
        manifest=_manifest(),
    ))
    original = gateway._file.read_bytes()
    invalid = _manifest()
    invalid["schema_version"] = 99

    with pytest.raises(ManifestValidationError):
        gateway.register(ConnectionRecord(
            name="existing",
            kind="agent",
            url="https://other.example/v1",
            manifest=invalid,
        ))

    assert gateway._file.read_bytes() == original
    assert gateway.get("existing").url == "https://agent.example/v1"


def test_gateway_ignores_invalid_persisted_manifest_without_losing_other_records(
    tmp_path, caplog
):
    path = tmp_path / "registry.json"
    valid = ConnectionRecord(
        name="valid",
        kind="agent",
        url="https://agent.example/v1",
        manifest=_manifest(),
    ).to_dict()
    invalid = {
        "name": "invalid",
        "kind": "agent",
        "url": "https://other.example/v1",
        "manifest": {"schema_version": 99},
    }
    path.write_text(json.dumps([valid, invalid]), encoding="utf-8")

    gateway = ConnectionGateway(root=tmp_path)

    assert gateway.get("valid") is not None
    assert gateway.get("invalid") is None
    assert "ignoring invalid connection registry record" in caplog.text


class _FakeManifestResponse:
    status_code = 200

    def __init__(self, chunks, *, headers=None):
        self.headers = headers or {"content-type": "application/json"}
        self._chunks = chunks

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk


class _FakeManifestClient:
    options = None
    requests = []
    chunks = []
    headers = {"content-type": "application/json"}

    def __init__(self, **options):
        type(self).options = options

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    def stream(self, method, url, *, headers):
        type(self).requests.append((method, url, headers))
        return _FakeManifestResponse(type(self).chunks, headers=type(self).headers)


def _install_fake_manifest_client(monkeypatch, manifest):
    encoded = json.dumps(manifest).encode()
    _FakeManifestClient.requests = []
    _FakeManifestClient.chunks = [encoded[:17], encoded[17:]]
    _FakeManifestClient.headers = {
        "content-type": "application/json",
        "content-length": str(len(encoded)),
    }
    monkeypatch.setattr(gateway_module.httpx, "AsyncClient", _FakeManifestClient)


@pytest.mark.asyncio
async def test_gateway_discovery_is_egress_gated_and_persists_valid_manifest(
    monkeypatch, tmp_path
):
    gateway = ConnectionGateway(root=tmp_path)
    gateway.register(ConnectionRecord(
        name="remote",
        kind="agent",
        url="https://agent.example/v1?model=private",
        scope="network.agent",
    ))
    _install_fake_manifest_client(monkeypatch, _manifest())

    denied = await gateway.discover_agent_manifest("remote")

    assert denied["confirmation_required"] is True
    assert not _FakeManifestClient.requests
    assert gateway.get("remote").manifest is None

    discovered = await gateway.discover_agent_manifest("remote", confirmed=True)

    assert discovered["ok"] is True
    assert discovered["manifest"] == _manifest()
    assert _FakeManifestClient.requests == [
        (
            "GET",
            "https://agent.example/.well-known/moon-agent.json",
            {"Accept": "application/json"},
        )
    ]
    assert _FakeManifestClient.options == {
        "timeout": 5.0,
        "follow_redirects": False,
        "trust_env": False,
    }
    assert gateway.get("remote").manifest == _manifest()
    assert ConnectionGateway(root=tmp_path).get("remote").manifest == _manifest()


@pytest.mark.asyncio
async def test_gateway_discovery_rejects_bad_json_contract_without_replacing_manifest(
    monkeypatch, tmp_path
):
    gateway = ConnectionGateway(root=tmp_path)
    gateway.register(ConnectionRecord(
        name="remote",
        kind="agent",
        url="https://agent.example/v1",
        scope="network.agent",
        manifest=_manifest(),
    ))
    invalid = _manifest()
    invalid["schema_version"] = 2
    _install_fake_manifest_client(monkeypatch, invalid)

    result = await gateway.discover_agent_manifest("remote", confirmed=True)

    assert result["ok"] is False
    assert "invalid agent manifest" in result["error"]
    assert gateway.get("remote").manifest == _manifest()


@pytest.mark.asyncio
async def test_gateway_discovery_rejects_oversized_manifest_before_json_parse(
    monkeypatch, tmp_path
):
    gateway = ConnectionGateway(root=tmp_path)
    gateway.register(ConnectionRecord(
        name="remote",
        kind="agent",
        url="https://agent.example/v1",
        scope="network.agent",
    ))
    _FakeManifestClient.chunks = [b"x" * (MAX_MANIFEST_BYTES + 1)]
    _FakeManifestClient.headers = {
        "content-type": "application/json",
        "content-length": "1",
    }
    monkeypatch.setattr(gateway_module.httpx, "AsyncClient", _FakeManifestClient)

    result = await gateway.discover_agent_manifest("remote", confirmed=True)

    assert result["ok"] is False
    assert "32768-byte" in result["error"]
    assert gateway.get("remote").manifest is None


@pytest.mark.asyncio
async def test_global_connector_inspects_declared_manifest_without_network(tmp_path):
    gateway = ConnectionGateway(root=tmp_path)
    gateway.register(ConnectionRecord(
        name="research-agent",
        kind="agent",
        url="https://agent.example/v1",
        manifest=_manifest(),
    ))
    tool = GlobalConnectorTool(gateway)

    output = await tool.execute(action="inspect", name="research-agent")

    assert "not independently verified" in output
    assert '"name": "Research Agent"' in output


@pytest.mark.asyncio
async def test_global_connector_rejects_invalid_manifest(tmp_path):
    tool = GlobalConnectorTool(ConnectionGateway(root=tmp_path))
    invalid = _manifest()
    invalid["schema_version"] = 4

    output = await tool.execute(
        action="connect",
        name="peer",
        kind="agent",
        url="http://127.0.0.1:9/v1",
        manifest=invalid,
    )

    assert "invalid agent manifest" in output
    assert tool._gw.get("peer") is None


@pytest.mark.asyncio
async def test_global_connector_inspection_reports_missing_manifest(tmp_path):
    tool = GlobalConnectorTool(ConnectionGateway(root=tmp_path))
    tool._gw.register(ConnectionRecord(
        name="legacy",
        kind="agent",
        url="https://agent.example/v1",
    ))

    output = await tool.execute(action="inspect", name="legacy")

    assert "no declared capability manifest" in output
    assert "has not been queried" in output


@pytest.mark.asyncio
async def test_global_connector_discovery_rejects_model_supplied_confirmation(
    monkeypatch, tmp_path
):
    gateway = ConnectionGateway(root=tmp_path)
    gateway.register(ConnectionRecord(
        name="remote",
        kind="agent",
        url="https://agent.example/v1",
    ))

    def unexpected_http_client(**_options):
        raise AssertionError("unapproved manifest discovery must not issue a request")

    monkeypatch.setattr(gateway_module.httpx, "AsyncClient", unexpected_http_client)
    tool = GlobalConnectorTool(gateway)
    class _Registry:
        def all(self):
            return [tool]

        def get(self, name):
            return tool if name == tool.name else None

    manager = ToolManager(_Registry())

    result = await manager.run(
        "global_connector",
        {"action": "discover", "name": "remote", "confirmed": True},
    )

    assert "requires egress authorization" in result.output
