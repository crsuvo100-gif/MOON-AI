"""Phase 1: Universal Agent Connector -- test suite (revision, API-correct).

Tests the real multi-protocol connector module against its actual public
API (RestConnector, WebSocketConnector, LocalIpcConnector, McpConnector,
AcpSubprocessConnector) plus the federation AgentConnector and the
registry/permission layer. Runs fully offline with no live services.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

# Ensure the MOON root is importable (tests run from the MOON project root).
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ---------------------------------------------------------------------------
# App-level packages (real implementation units)
# ---------------------------------------------------------------------------
from app.agent_factory.models import AgentMetadata, RiskLevel  # noqa: E402
from app.connector.connectors import (  # noqa: E402
    CallResult as ConnectorCallResult,
    HTTPConnector,
    MCPConnector as FoundationMCPConnector,
    WebSocketConnector as NetworkWebSocketConnector,
)
from app.connector.manifest import (  # noqa: E402
    ManifestValidationError,
    validate_agent_manifest,
)
from app.connector.permission import (  # noqa: E402
    ConnectorPermissionManager,
    EgressDecision,
    PolicyLevel,
    PermissionManager,
)
from app.connector.universal_agent_connector import (  # noqa: E402
    AcpSubprocessConnector,
    AgentConnector,
    AgentRegistry,
    CapabilityManifest,
    ConnectorPermissionManager as UniversalConnectorPermissionManager,
    LocalIpcConnector,
    RestConnector,
    TaskRecord,
    TaskStatus,
    McpConnector,
    WebSocketConnector as ProtocolWebSocketConnector,
)

# We intentionally use the real foundation classes, not aliases, so the suite
# exercises the implementation endpoints in app/connector rather than stubs.


# ---------------------------------------------------------------------------
# Fixtures (isolated per-test registry root under pytest's tmp_path)
# ---------------------------------------------------------------------------


@pytest.fixture()
def registry(tmp_path):
    """A registry persisted under a per-test temp directory."""
    return AgentRegistry(root=tmp_path / "agent_connector")


@pytest.fixture()
def connector(registry):
    """The universal AgentConnector backed by the isolated registry."""
    return AgentConnector(registry=registry)


# ---------------------------------------------------------------------------
# AgentMetadata / RiskLevel
# ---------------------------------------------------------------------------


class TestAgentMetadata:
    """AgentMetadata uses `id` (not agent_id) and caps as list[str]."""

    def test_fields(self):
        meta = AgentMetadata(
            id="agent-1",
            name="Test Agent",
            version="1.0.0",
            capabilities=["read:*.txt", "write:*.md"],
            risk_level=RiskLevel.HIGH.value,
        )
        assert meta.id == "agent-1"
        assert meta.name == "Test Agent"
        assert meta.version == "1.0.0"
        assert meta.risk_level == "high"
        assert meta.capabilities == ["read:*.txt", "write:*.md"]

    def test_to_dict(self):
        meta = AgentMetadata(id="a", name="N", capabilities=["x"], risk_level="low")
        d = meta.to_dict()
        assert d["id"] == "a"
        assert d["name"] == "N"
        assert d["capabilities"] == ["x"]

    def test_from_dict_roundtrip(self):
        original = AgentMetadata(
            id="agent-1",
            name="Agent One",
            version="2.3.4",
            capabilities=["code:*.py"],
            risk_level=RiskLevel.MEDIUM.value,
        )
        restored = AgentMetadata.from_dict(original.to_dict())
        assert restored == original


# ---------------------------------------------------------------------------
# Manifest validation (app.connector.manifest)
# ---------------------------------------------------------------------------


class TestManifestValidationError:
    def test_is_value_error(self):
        assert issubclass(ManifestValidationError, ValueError)


class TestValidateAgentManifest:
    """validate_agent_manifest() validates a raw-capability manifest dataclass."""

    def test_valid_manifest(self):
        manifest = {
            "schema_version": 1,
            "agent_id": "test-agent",
            "name": "Test Agent",
            "version": "1.0.0",
            "protocol": "openai-chat-completions",
            "description": "A test agent",
            "capabilities": [
                {
                    "name": "read",
                    "description": "Read files",
                    "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
                    "output_schema": {"type": "string"},
                }
            ],
        }
        result = validate_agent_manifest(manifest)
        assert result["schema_version"] == 1
        assert result["agent_id"] == "test-agent"
        assert len(result["capabilities"]) == 1

    def test_invalid_schema_version(self):
        manifest = {
            "schema_version": 2,
            "agent_id": "test-agent",
            "name": "Test Agent",
            "version": "1.0.0",
            "protocol": "openai-chat-completions",
            "capabilities": [],
        }
        with pytest.raises(ManifestValidationError):
            validate_agent_manifest(manifest)

    def test_invalid_agent_id(self):
        manifest = {
            "schema_version": 1,
            "agent_id": "agent id with spaces",  # invalid identifier
            "name": "Test Agent",
            "version": "1.0.0",
            "protocol": "openai-chat-completions",
            "capabilities": [],
        }
        with pytest.raises(ManifestValidationError):
            validate_agent_manifest(manifest)

    def test_invalid_protocol(self):
        manifest = {
            "schema_version": 1,
            "agent_id": "test-agent",
            "name": "Test Agent",
            "version": "1.0.0",
            "protocol": "websocket",
            "capabilities": [],
        }
        with pytest.raises(ManifestValidationError):
            validate_agent_manifest(manifest)

    def test_unsupported_field(self):
        manifest = {
            "schema_version": 1,
            "agent_id": "test-agent",
            "name": "Test Agent",
            "version": "1.0.0",
            "protocol": "openai-chat-completions",
            "capabilities": [],
            "extra_field": "should fail",
        }
        with pytest.raises(ManifestValidationError):
            validate_agent_manifest(manifest)

    def test_capability_name_must_be_unique(self):
        manifest = {
            "schema_version": 1,
            "agent_id": "test-agent",
            "name": "Test Agent",
            "version": "1.0.0",
            "protocol": "openai-chat-completions",
            "capabilities": [
                {"name": "read", "description": "Read", "input_schema": {"type": "object"},
                 "output_schema": {"type": "string"}},
                {"name": "read", "description": "Read again", "input_schema": {"type": "object"},
                 "output_schema": {"type": "string"}},
            ],
        }
        with pytest.raises(ManifestValidationError):
            validate_agent_manifest(manifest)

    def test_capability_missing_required_property(self):
        manifest = {
            "schema_version": 1,
            "agent_id": "test-agent",
            "name": "Test Agent",
            "version": "1.0.0",
            "protocol": "openai-chat-completions",
            "capabilities": [
                {
                    "name": "read",
                    "description": "Read",
                    "output_schema": {"type": "string"},
                }
            ],
        }
        with pytest.raises(ManifestValidationError):
            validate_agent_manifest(manifest)

    def test_manifest_too_large(self):
        base = {
            "schema_version": 1,
            "agent_id": "test-agent",
            "name": "Test Agent",
            "version": "1.0.0",
            "protocol": "openai-chat-completions",
            "capabilities": [],
        }
        # Serialize a payload far above the 100 KB cap
        payload = json.dumps(base, separators=(",", ":")) * 2000
        with pytest.raises(ManifestValidationError):
            validate_agent_manifest(payload)


# ---------------------------------------------------------------------------
# CapabilityManifest (universal)
# ---------------------------------------------------------------------------


class TestCapabilityManifest:
    def _make_manifest(self, **kwargs):
        defaults = {
            "agent_id": "test-agent",
            "agent_name": "Test Agent",
            "protocol": "local",
            "endpoint": "/agents/test-agent",
            "agent_capabilities": {"tools": True, "memory": False},
            "supported_protocols": ["local", "rest", "ws", "mcp", "acp"],
        }
        defaults.update(kwargs)
        return CapabilityManifest(**defaults)

    def test_validate_success(self):
        cm = self._make_manifest()
        ok, msg = cm.validate()
        assert ok is True
        assert msg == "valid"

    def test_validate_missing_agent_id(self):
        cm = CapabilityManifest(
            agent_name="Test Agent",
            protocol="local",
            agent_capabilities={"tools": True},
            supported_protocols=["local"],
        )
        ok, msg = cm.validate()
        assert ok is False
        assert "agent_id" in msg

    def test_validate_invalid_protocol(self):
        cm = self._make_manifest(protocol="ftp")
        ok, msg = cm.validate()
        assert ok is False

    def test_validate_empty_capabilities(self):
        cm = self._make_manifest(agent_capabilities={})
        ok, msg = cm.validate()
        assert ok is False


# ---------------------------------------------------------------------------
# AgentRegistry
# ---------------------------------------------------------------------------


class TestAgentRegistry:
    def _register(self, registry, agent_id="r1", name="Registry Agent"):
        metadata = AgentMetadata(
            id=agent_id,
            name=name,
            version="1.0.0",
            capabilities=["read:*.txt", "write:*.md"],
            risk_level=RiskLevel.HIGH.value,
        )
        manifest = CapabilityManifest(
            agent_id=agent_id,
            agent_name=name,
            protocol="local",
            endpoint=f"/agents/{agent_id}",
            agent_capabilities={"tools": True},
            supported_protocols=["local"],
            risk_level=RiskLevel.HIGH.value,
        )
        return registry.register_agent(metadata, manifest)

    def test_register_agent(self, registry):
        registered = self._register(registry)
        assert registered is not None
        assert registry.agents()[0]["id"] == "r1"

    def test_register_duplicate_raises(self, registry):
        self._register(registry)
        with pytest.raises(ValueError, match="already registered"):
            self._register(registry)

    def test_remove_agent(self, registry):
        self._register(registry)
        assert registry.remove_agent("r1") is True
        assert len(registry.agents()) == 0

    def test_task_roundtrip(self, registry):
        self._register(registry, agent_id="t1")
        record = TaskRecord(
            task_id="task-1",
            agent_id="t1",
            agent_name="Registry Agent",
            kind="code",
            payload={"action": "read", "path": "/tmp/test.txt"},
        )
        registry.record_task(record)
        retrieved = registry.task_by_id("task-1")
        assert retrieved is not None
        assert retrieved.task == record.task
        assert retrieved.status == "pending"

        registry.complete_task("task-1")
        completed = registry.task_by_id("task-1")
        assert completed is not None
        assert completed.status == "completed"

    def test_get_agent_by_id(self, registry):
        self._register(registry)
        found = registry.get_agent_by_id("r1")
        assert found is not None
        assert found["id"] == "r1"
        assert registry.get_agent_by_id("nonexistent") is None


# ---------------------------------------------------------------------------
# TaskRecord and TaskStatus
# ---------------------------------------------------------------------------


class TestTaskRecord:
    def test_create(self):
        record = TaskRecord(
            task_id="task-1",
            agent_id="agent-1",
            agent_name="Agent One",
            kind="code",
            payload={"action": "read", "path": "/tmp/test.txt"},
        )
        assert record.task_id == "task-1"
        assert record.status == "pending"
        assert record.attempts == 0

    def test_to_dict(self):
        record = TaskRecord(
            task_id="t1",
            agent_id="a1",
            agent_name="A",
            kind="code",
            payload={"x": 1},
            attempts=2,
        )
        d = record.to_dict()
        assert d["task_id"] == "t1"
        assert d["attempts"] == 2


class TestTaskStatus:
    def test_record_and_events(self):
        ts = TaskStatus()
        ts.record("task-1", "started", {"detail": "x"})
        ts.record("task-1", "completed", {"detail": "y"})
        events = ts.events("task-1")
        assert len(events) == 2
        assert events[0]["event"] == "started"

    def test_events_empty_for_unknown(self):
        ts = TaskStatus()
        assert ts.events("unknown") == []


# ---------------------------------------------------------------------------
# AgentConnector - universal orchestrator
# ---------------------------------------------------------------------------


class TestAgentConnector:
    def test_register_and_inspect(self, connector):
        metadata = AgentMetadata(
            id="ac-1",
            name="Connect Agent",
            version="1.0.0",
            capabilities=["read:*.txt"],
            risk_level=RiskLevel.MEDIUM.value,
        )
        manifest = CapabilityManifest(
            agent_id="ac-1",
            agent_name="Connect Agent",
            protocol="local",
            endpoint="/agents/ac-1",
            agent_capabilities={"tools": True},
            supported_protocols=["local"],
        )
        registered = connector.register(metadata, manifest)
        assert registered is not None
        assert registered.id == "ac-1"

        caps = connector.inspect_capabilities("ac-1")
        assert caps.get("agent_id") == "ac-1"
        assert caps.get("protocol") == "local"

    def test_register_without_manifest(self, connector):
        metadata = AgentMetadata(
            id="ac-2",
            name="Connect Agent",
            version="1.0.0",
            capabilities=["read:*.txt"],
            risk_level=RiskLevel.MEDIUM.value,
        )
        connector.register(metadata)
        agents = connector.discover()
        assert any(a["id"] == "ac-2" for a in agents)

    def test_register_uses_permission_level(self, connector):
        metadata = AgentMetadata(
            id="ac-3",
            name="Connect Agent",
            version="1.0.0",
            capabilities=[],
            risk_level=RiskLevel.MEDIUM.value,
        )
        registered = connector.register(metadata, permission_level="none")
        assert registered is not None
        assert registered.id == "ac-3"

    def test_set_agent_policy(self, connector):
        connector.set_agent_policy("ac-1", "allow")
        # The universal ConnectorPermissionManager evaluates policy overrides
        assert connector.permission_manager.evaluate(
            "ac-1", "network.egress", "anywhere"
        ) == "allow"

    def test_discover_empty(self, connector):
        assert connector.discover() == []

    def test_adapters_fallback_local(self, connector):
        adapter = connector._factory("local-agent", {"manifest": {"protocol": "local"}})
        assert adapter is not None
        assert adapter.connected is False


# ---------------------------------------------------------------------------
# CallResult (connector.connectors)
# ---------------------------------------------------------------------------


class TestCallResult:
    def test_connector_call_result(self):
        result = ConnectorCallResult(
            ok=True, status=200, data={"output": "hello"},
            error=None, headers={"Content-Type": "application/json"},
        )
        assert result.ok is True
        assert result.status == 200
        assert result.data == {"output": "hello"}
        assert result.error is None
        assert result.headers["Content-Type"] == "application/json"

    def test_connector_call_result_error(self):
        result = ConnectorCallResult(ok=False, error="boom", data=None)
        assert result.ok is False
        assert result.error == "boom"


# ---------------------------------------------------------------------------
# Federation AgentConnector (connectors.py) -- real HTTP state
# ---------------------------------------------------------------------------


class TestFederationAgentConnector:
    def test_construction(self):
        conn = HTTPConnector("http://localhost:8080/v1", headers={"X-Test": "1"}, timeout=30.0)
        assert conn._base == "http://localhost:8080/v1"

    async def test_health(self):
        conn = HTTPConnector("http://127.0.0.1:1")
        result = await conn.health()
        assert isinstance(result, ConnectorCallResult)
        assert result.ok is False  # no live server -> not ok, error set


# ---------------------------------------------------------------------------
# HTTPConnector, NetworkWebSocketConnector, FoundationMCPConnector
# ---------------------------------------------------------------------------


class TestHTTPConnector:
    def test_construction(self):
        conn = HTTPConnector("http://example.com", headers={"X-Test": "1"}, timeout=30.0)
        assert conn._base == "http://example.com"

    async def test_call(self):
        conn = HTTPConnector("http://example.com")
        result = await conn.call("GET", "/health")
        assert isinstance(result, ConnectorCallResult)

    async def test_health(self):
        conn = HTTPConnector("http://127.0.0.1:1")
        result = await conn.health()
        assert isinstance(result, ConnectorCallResult)


class TestNetworkWebSocketConnector:
    def test_construction(self):
        conn = NetworkWebSocketConnector("ws://example.com/ws", timeout=10.0)
        assert conn._url == "ws://example.com/ws"

    async def test_send_recv(self):
        conn = NetworkWebSocketConnector("ws://example.com/ws")
        result = await conn.send_recv("hello")
        assert isinstance(result, ConnectorCallResult)


class TestFoundationMCPConnector:
    def test_construction_url(self):
        conn = FoundationMCPConnector("http://localhost:8080", timeout=30.0)
        assert conn._url == "http://localhost:8080"

    async def test_aiohttp_context_manager(self):
        conn = FoundationMCPConnector("http://localhost:8080")
        result = await conn.connect()
        assert isinstance(result, ConnectorCallResult)
        await conn.close()


# ---------------------------------------------------------------------------
# RestConnector (universal adapter)
# ---------------------------------------------------------------------------


class TestRestConnector:
    def test_construction_and_capabilities(self):
        conn = RestConnector("agent-1", {"endpoint": "http://localhost"})
        assert conn.agent_id == "agent-1"
        caps = conn.capabilities()
        assert caps.get("protocol") == "rest"
        assert caps.get("chat_completions") is True

    def test_connect_without_endpoint(self):
        conn = RestConnector("agent-1", {"endpoint": ""})
        assert conn.connect(None) is False

    def test_disconnect(self):
        conn = RestConnector("agent-1", {"endpoint": "http://localhost"})
        # connect() returns False without a live server; disconnect() still works
        conn.connect(None)
        assert conn.disconnect() is True
        assert conn.connected is False

    def test_ping_not_connected(self):
        conn = RestConnector("agent-1", {"endpoint": "http://localhost"})
        ok, msg = conn.ping()
        assert ok is False
        assert msg == "not connected"

    def test_delegate_not_connected(self):
        conn = RestConnector("agent-1", {"endpoint": "http://localhost"})
        result = conn.delegate({"type": "code"})
        assert result.ok is False
        assert "not connected" in result.error


# ---------------------------------------------------------------------------
# ProtocolWebSocketConnector (universal adapter)
# ---------------------------------------------------------------------------


class TestProtocolWebSocketConnector:
    def test_construction_and_capabilities(self):
        conn = ProtocolWebSocketConnector("agent-1", {"endpoint": "ws://localhost"})
        assert conn.agent_id == "agent-1"
        caps = conn.capabilities()
        assert caps.get("protocol") == "websocket"
        assert caps.get("websocket") is True

    def test_connect_disconnect(self):
        conn = ProtocolWebSocketConnector("agent-1", {"endpoint": "ws://localhost"})
        conn.connect(None)  # permission-gated: localhost is allowlisted by default
        assert conn.connected is True
        assert conn.disconnect() is True
        assert conn.connected is False

    def test_ping_not_connected(self):
        conn = ProtocolWebSocketConnector("agent-1", {})
        ok, msg = conn.ping()
        assert ok is False
        assert msg == "not connected"

    def test_delegate_not_connected(self):
        conn = ProtocolWebSocketConnector("agent-1", {})
        result = conn.delegate({"type": "code"})
        assert result.ok is False
        assert "not connected" in result.error


# ---------------------------------------------------------------------------
# LocalIpcConnector (universal adapter)
# ---------------------------------------------------------------------------


class TestLocalIpcConnector:
    def test_construction_and_capabilities(self):
        conn = LocalIpcConnector("agent-1", {"command": ["sleep", "5"]})
        assert conn.agent_id == "agent-1"
        caps = conn.capabilities()
        assert caps.get("protocol") == "localipc"
        assert caps.get("sandboxed") is True

    def test_connect_without_command(self):
        conn = LocalIpcConnector("agent-1", {})
        assert conn.connect(None) is False

    def test_connect_with_command(self):
        # Permission manager must answer is_allowed(action, scope)
        class _StubPerm:
            def is_allowed(self, action, scope):
                return True

        conn = LocalIpcConnector("agent-1", {"command": ["true"]})
        ok = conn.connect(_StubPerm())
        assert isinstance(ok, bool)
        if ok:
            conn.disconnect()

    def test_ping_not_connected(self):
        conn = LocalIpcConnector("agent-1", {})
        ok, msg = conn.ping()
        assert ok is False

    def test_delegate_not_connected(self):
        conn = LocalIpcConnector("agent-1", {})
        result = conn.delegate({"type": "code"})
        assert result.ok is False
        assert "not connected" in result.error


# ---------------------------------------------------------------------------
# McpConnector (universal adapter)
# ---------------------------------------------------------------------------


class TestMcpConnector:
    def test_construction(self):
        conn = McpConnector("agent-1", {"command": ["mcp-server"]})
        assert conn.agent_id == "agent-1"
        assert conn.session is None

    def test_connect_without_command(self):
        conn = McpConnector("agent-1", {})
        assert conn.connect(None) is False

    def test_disconnect(self):
        conn = McpConnector("agent-1", {"command": ["mcp-server"]})
        # connect() returns False without a live MCP server; disconnect() works
        conn.connect(None)
        assert conn.disconnect() is True
        assert conn.connected is False

    def test_ping_not_connected(self):
        conn = McpConnector("agent-1", {})
        ok, msg = conn.ping()
        assert ok is False

    def test_delegate_not_connected(self):
        conn = McpConnector("agent-1", {})
        result = conn.delegate({"type": "code"})
        assert result.ok is False
        assert "not connected" in result.error


# ---------------------------------------------------------------------------
# AcpSubprocessConnector (universal adapter)
# ---------------------------------------------------------------------------


class TestAcpSubprocessConnector:
    def test_construction(self):
        conn = AcpSubprocessConnector("agent-1", {"command": ["python", "-m", "http.server"]})
        assert conn.agent_id == "agent-1"

    def test_acp_handshake_not_connected(self):
        conn = AcpSubprocessConnector("agent-1", {})
        ok, msg = conn._acp_handshake()
        assert ok is False
        assert "not connected" in msg

    def test_connect_disconnect(self):
        conn = AcpSubprocessConnector("agent-1", {"command": ["python", "-m", "http.server"]})
        ok = conn.connect(None)  # returns True without a live server
        assert isinstance(ok, bool)
        if ok:
            assert conn.disconnect() is True
            assert conn.connected is False

    def test_ping_not_connected(self):
        conn = AcpSubprocessConnector("agent-1", {})
        ok, msg = conn.ping()
        assert ok is False

    def test_delegate_not_connected(self):
        conn = AcpSubprocessConnector("agent-1", {})
        result = conn.delegate({"type": "code"})
        assert result.ok is False
        assert "not connected" in result.error


# ---------------------------------------------------------------------------
# ConnectorPermissionManager + EgressDecision (permission layer)
# ---------------------------------------------------------------------------


class TestConnectorPermissionManager:
    def test_may_auto_secrets_read_false(self):
        perm = ConnectorPermissionManager()
        assert perm.may_auto("secrets.read") is False

    def test_may_auto_allowlisted(self):
        old = os.environ.get("ALLOWED_EGRESS_HOSTS")
        os.environ["ALLOWED_EGRESS_HOSTS"] = "allowed.example.com"
        try:
            perm = ConnectorPermissionManager()
            assert perm.may_auto("network.egress", "allowed.example.com") is True
            assert perm.may_auto("network.egress", "not-allowlisted.example.com") is False
        finally:
            if old is None:
                os.environ.pop("ALLOWED_EGRESS_HOSTS", None)
            else:
                os.environ["ALLOWED_EGRESS_HOSTS"] = old

    def test_egress_decision_secrets_read_never(self):
        perm = ConnectorPermissionManager()
        decision = perm.egress_decision("some-host", scope="secrets.read")
        assert decision.allowed is False
        assert decision.tier == PolicyLevel.NEVER

    def test_egress_decision_not_allowlisted(self):
        perm = ConnectorPermissionManager()
        decision = perm.egress_decision("not-allowlisted.example.com")
        assert decision.allowed is False
        assert decision.tier == PolicyLevel.CONFIRMATION

    def test_register_agent_policy_and_evaluate(self):
        perm = UniversalConnectorPermissionManager()
        perm.register_agent_policy("agent-1", "allow")
        assert perm.evaluate("agent-1", "network.egress", "anywhere") == "allow"
        perm.register_agent_policy("agent-1", "deny")
        assert perm.evaluate("agent-1", "network.egress", "anywhere") == "deny"


# ---------------------------------------------------------------------------
# Integration: full workflow through a single connector + registry
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_full_workflow(self, connector):
        # 1. Register an agent via the universal connector
        metadata = AgentMetadata(
            id="int-1",
            name="Integration Agent",
            version="1.0.0",
            capabilities=["read:*.py", "write:*.md"],
            risk_level=RiskLevel.HIGH.value,
        )
        manifest = CapabilityManifest(
            agent_id="int-1",
            agent_name="Integration Agent",
            protocol="local",
            endpoint="/agents/int-1",
            agent_capabilities={"tools": True, "memory": False},
            supported_protocols=["local", "rest", "ws", "mcp", "acp"],
        )
        registered = connector.register(metadata, manifest)
        assert registered is not None
        assert registered.id == "int-1"

        # 2. Verify the registry sees the agent
        registry = connector.registry
        assert len(registry.agents()) == 1

        # 3. Task lifecycle through the registry
        record = TaskRecord(
            task_id="task-1",
            agent_id="int-1",
            agent_name="Integration Agent",
            kind="code",
            payload={"action": "read", "path": "/tmp/integration.txt"},
        )
        registry.record_task(record)
        assert registry.task_by_id("task-1").status == "pending"
        registry.complete_task("task-1")
        assert registry.task_by_id("task-1").status == "completed"

        # 4. Connector policy management
        connector.set_agent_policy("int-1", "allow")
        assert connector.permission_manager.evaluate(
            "int-1", "network.egress", "anywhere"
        ) == "allow"
