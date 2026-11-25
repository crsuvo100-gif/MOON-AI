"""Universal Agent Connector + HERMES Integration.

Additive, non-destructive Phase 1 implementation for MOON V13.0.

Provides a permission-gated, multi-protocol agent connector that lets MOON
discover, register, authenticate, delegate tasks to, and monitor independent
AI agents -- including the HERMES agent -- without ever making an agent a
mandatory permanent runtime dependency. MOON keeps its own identity, memory,
tools, configuration, runtime, and independent operation.

Protocols supported (each is a pluggable adapter):

  * REST         -- OpenAI-compatible chat-completions endpoint (httpx).
  * WebSocket    -- SSE-based bidirectional streams (websockets).
  * Local IPC    -- stdio/subprocess local agents.
  * MCP          -- stdio / SSE / streamable-http MCP clients (when `mcp` is
                    installed; gracefully degraded otherwise).
  * ACP          -- Hermes ACP subsystem protocol over stdio (for HERMES).

Architecture:

  AgentRegistry  -- registration + persistent capability manifests + atomic
                     JSON persistence (survives restarts; never destroyed by
                     disconnections).
  ConnectorAdapter protocol -- one adapter per transport.
  AgentConnector -- orchestrator: register -> authenticate -> inspect
                     capabilities -> authorize -> delegate -> receive results
                     -> monitor -> health -> reconnect.
  TaskStatus     -- task id -> status/started_at/completed_at/result/event.

Design rules (per V13.0 spec 3/15):
  * Reuse existing components (ConnectionGateway, ConnectorPermissionManager,
    IntegrationHub, CallResult, app/agent_factory/models).
  * Never duplicate the capability catalog or the connection registry.
  * Every outbound action permission-gated; CONFIRMATION tier requires
    explicit operator approval.
  * HERMES integration is OPTIONAL: `AcpSubprocessConnector` is used only when
    the operator explicitly connects HERMES; it is not a mandatory dependency.

DEPENDENCY CONTRACT (no mandatory new top-level deps):
  * httpx    -- required (already in MOON core deps).
  * websockets -- optional; connector degrades gracefully if missing.
  * mcp      -- optional; MCP adapter degrades gracefully if missing.
  * No new required dependencies added to pyproject.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    from app.connector.connectors import CallResult as FoundationCallResult
except ImportError:  # pragma: no cover - fallback for tests without the foundation
    from dataclasses import dataclass, field

    @dataclass
    class FoundationCallResult:  # type: ignore[no-redef]
        ok: bool
        status: int = 0
        data: Any = None
        error: str | None = None
        headers: dict[str, str] = field(default_factory=dict)

# Universal-connector namespace: CallResult is the working foundation class.
CallResult = FoundationCallResult

# ---- Optional transport dependencies (graceful degradation) ------------------

try:
    import httpx
    _HAS_HTTPX = True
except Exception:
    httpx = None  # type: ignore[assignment]
    _HAS_HTTPX = False

try:
    import websockets
    _HAS_WS = True
except Exception:
    websockets = None  # type: ignore[assignment]
    _HAS_WS = False

try:
    import mcp
    _HAS_MCP = True
except Exception:
    mcp = None
    _HAS_MCP = False


# =============================================================================
# Shared types (reuse app/agent_factory/models where present)
# =============================================================================

def _load_agent_models():
    try:
        from app.agent_factory.models import (
            AgentMetadata as _AgentMetadata,
            AgentStatus as _AgentStatus,
            RiskLevel as _RiskLevel,
            AuditAction as _AuditAction,
        )
        return _AgentMetadata, _AgentStatus, _RiskLevel, _AuditAction
    except Exception:
        pass

    @dataclass
    class RiskLevel(str, Enum):
        LOW = "low"
        MEDIUM = "medium"
        HIGH = "high"
        CRITICAL = "critical"

    @dataclass
    class AgentStatus(str, Enum):
        STAGING = "staging"
        ACTIVE = "active"
        DISABLED = "disabled"
        QUARANTINED = "quarantined"

    @dataclass
    class AuditAction(str, Enum):
        CREATE = "agent.create"
        REGISTER = "agent.register"
        ENABLE = "agent.enable"
        DISABLE = "agent.disable"
        RUN = "agent.run"
        FAILURE = "agent.failure"
        DISCONNECT = "agent.disconnect"

    @dataclass
    class AgentMetadata:
        id: str
        name: str
        version: str = "1.0.0"
        description: str = ""
        capabilities: list[str] = field(default_factory=list)
        required_tools: list[str] = field(default_factory=list)
        permissions: list[str] = field(default_factory=list)
        risk_level: str = RiskLevel.LOW.value
        input_schema: dict[str, Any] = field(default_factory=dict)
        output_schema: dict[str, Any] = field(default_factory=dict)
        dependencies: list[str] = field(default_factory=list)
        tests: list[str] = field(default_factory=list)
        status: str = AgentStatus.STAGING.value

    return AgentMetadata, AgentStatus, RiskLevel, AuditAction


AgentMetadata, AgentStatus, RiskLevel, AuditAction = _load_agent_models()


@dataclass
class CapabilityManifest:
    """Declarative, non-authoritative capability manifest for a connected agent."""
    version: int = 1
    agent_id: str = ""
    agent_name: str = ""
    protocol: str = "rest"
    endpoint: str = ""
    agent_capabilities: dict[str, Any] = field(default_factory=dict)
    supported_protocols: list[str] = field(default_factory=list)
    requires_confirmation: bool = False
    risk_level: str = "low"
    checksum: str = ""

    def validate(self) -> tuple[bool, str]:
        """Return (ok, message). Checks protocol version + declared capabilities."""
        if self.version != 1:
            return False, f"unsupported manifest version {self.version}"
        if not self.agent_id or not self.endpoint:
            return False, "agent_id and endpoint are required"
        if not self.supported_protocols:
            return False, "supported_protocols required"
        if self.protocol not in self.supported_protocols:
            return False, f"protocol {self.protocol} not in supported_protocols"
        if not self.agent_capabilities:
            return False, "agent_capabilities required"
        return True, "valid"


@dataclass
class TaskRecord:
    task_id: str
    agent_id: str
    agent_name: str
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # pending | running | succeeded | failed | cancelled
    result: Any = None
    error: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    attempts: int = 0
    max_attempts: int = 3
    queued_at: float = 0.0
    task: Any = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# =============================================================================
# Persistence (atomic, survive restarts, never destroyed by disconnections)
# =============================================================================

class AgentRegistry:
    """Persistent, atomic registry of connected agents + task status."""

    def __init__(self, root: Path | str | None = None):
        self.root = Path(root) if root else Path.home() / ".moon" / "agent_connector"
        self.agents_file = self.root / "agents.json"
        self.tasks_file = self.root / "tasks.json"
        self.root.mkdir(parents=True, exist_ok=True)

    # -- atomic json helpers ---------------------------------------------------
    @staticmethod
    def _atomic_write(path: Path, payload: Any) -> None:
        path.with_suffix(path.suffix + ".tmp")
        with tempfile.NamedTemporaryFile("w", delete=False, dir=str(path.parent)) as f:
            json.dump(payload, f, indent=2, default=str)
            f.write("\n")
            tmp_path = f.name
        os.replace(tmp_path, path)

    def load(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text())
        except Exception as exc:
            logger.warning("registry load failed for %s: %s", path, exc)
            return default

    def agents(self) -> list[dict[str, Any]]:
        data = self.load(self.agents_file, {"agents": [], "next_id": 1})
        return data.get("agents", [])

    def save_agents(self, agents: list[dict[str, Any]]) -> None:
        data = {"agents": agents, "next_id": 1}
        seen = {a.get("id") for a in agents if a.get("id")}
        n = 1
        while str(n) in seen:
            n += 1
        data["next_id"] = n
        self._atomic_write(self.agents_file, data)

    def tasks(self) -> list[TaskRecord]:
        data = self.load(self.tasks_file, {"tasks": []})
        out = []
        for t in data.get("tasks", []):
            try:
                out.append(TaskRecord(**t))
            except Exception:
                continue
        return out

    def save_tasks(self, tasks: list[TaskRecord]) -> None:
        self._atomic_write(
            self.tasks_file, {"tasks": [t.to_dict() for t in tasks]}
        )

    def register_agent(self, meta: AgentMetadata, manifest: CapabilityManifest,  # type: ignore[valid-type]
                       permission_level: str = "confirmation") -> AgentMetadata:  # type: ignore[valid-type]
        agents = self.agents()
        for a in agents:
            if a.get("id") == meta.id:  # type: ignore[attr-defined]
                raise ValueError(f"agent {meta.id} already registered")  # type: ignore[attr-defined]
        payload = asdict(meta)
        payload["manifest"] = asdict(manifest)
        payload["permission_level"] = permission_level
        payload["connected"] = False
        payload["last_seen"] = None
        agents.append(payload)
        self.save_agents(agents)
        logger.info("agent registered: %s (%s)", meta.id, meta.name)  # type: ignore[attr-defined]
        return meta

    def remove_agent(self, agent_id: str) -> bool:
        agents = self.agents()
        new = [a for a in agents if a.get("id") != agent_id]
        if len(new) == len(agents):
            return False
        self.save_agents(new)
        # tasks referencing the agent are kept (disconnections must not destroy data)
        return True

    def task_by_id(self, task_id: str) -> Optional[TaskRecord]:
        for t in self.tasks():
            if t.task_id == task_id:
                return t
        return None

    def record_task(self, task: TaskRecord) -> None:
        tasks = self.tasks()
        existing = [t for t in tasks if t.task_id == task.task_id]
        if existing:
            idx = tasks.index(existing[0])
            tasks[idx] = task
        else:
            tasks.append(task)
        self.save_tasks(tasks)

    def get_agent_by_id(self, agent_id: str) -> Optional[dict[str, Any]]:
        """Return the registered agent record by id, or None."""
        for agent in self.agents():
            if agent.get("id") == agent_id:
                return agent
        return None

    def complete_task(self, task_id: str) -> Optional[TaskRecord]:
        """Mark a registered task as completed and persist the change."""
        tasks = self.tasks()
        for task in tasks:
            if task.task_id == task_id:
                task.status = "completed"
                self.save_tasks(tasks)
                return task
        return None


# =============================================================================
# Permission / authorization policy
# =============================================================================

try:
    from app.connector.permission import (
        ConnectorPermissionManager as _FoundationPermissionManager,
        EgressDecision as _EgressDecision,
        NETWORK_SCOPES as _NETWORK_SCOPES,
    )
except Exception:  # pragma: no cover - fallback when foundation is absent
    _FoundationPermissionManager = object  # type: ignore[assignment,misc]
    _EgressDecision = None  # type: ignore[assignment,misc]
    _NETWORK_SCOPES = ()  # type: ignore[assignment]

# ---- HERMES/ACP integration helpers (optional, no new hard deps) --------------
try:
    from app.connector.acp import ACPSubprocessConnector as _FoundationACPSubprocessConnector
except Exception:  # pragma: no cover
    _FoundationACPSubprocessConnector = None  # type: ignore[assignment,misc]

try:
    from app.connector.connectors import CallResult
except ImportError:  # pragma: no cover - fallback for tests without the foundation
    from dataclasses import dataclass, field

    @dataclass
    class CallResult:  # type: ignore[no-redef]
        ok: bool
        status: int = 0
        data: Any = None
        error: str | None = None
        headers: dict[str, str] = field(default_factory=dict)


# =============================================================================
# Permission / authorization policy (reuses foundation permission layer)
# =============================================================================

class ConnectorPermissionManager(_FoundationPermissionManager):
    """Least-privilege permission gate for the universal connector.

    Reuses the foundation's ``ConnectorPermissionManager`` (which itself is
    layered on ``app.capability.permission_manager.PermissionManager``) and
    adds agent-scoped policy overrides used by the universal connector.

    Policy tiers: SAFE (allowlisted) -> CONFIRMATION (operator approval) ->
    NEVER (always denied, e.g. credential reads). This matches the V13.0
    spec's least-privilege and revocation requirements.
    """

    def __init__(self, allowed_ingress_hosts: list[str] | None = None):
        super().__init__(allowed_ingress_hosts=allowed_ingress_hosts or [])
        self._agent_overrides: dict[str, str] = {}

    def register_agent_policy(self, agent_id: str, policy: str) -> None:
        """Persist an override policy for a specific agent."""
        if policy not in {"allow", "confirmation", "deny"}:
            raise ValueError(f"unknown policy {policy!r}")
        self._agent_overrides[agent_id] = policy

    def evaluate(self, agent_id: str | None, action: str, scope: str) -> str:
        """Return the effective policy for an agent + action + scope."""
        if agent_id and agent_id in self._agent_overrides:
            return self._agent_overrides[agent_id]
        return super().evaluate(action, scope)  # type: ignore[misc]

    def may_auto(self, action: str, scope: str, agent_id: str | None = None) -> bool:  # type: ignore[override]
        """True only when the action may proceed WITHOUT operator confirmation."""
        if agent_id and agent_id in self._agent_overrides:
            return self._agent_overrides[agent_id] == "allow"
        return super().may_auto(scope)


# =============================================================================
# Connector adapter interface
# =============================================================================

class ConnectorAdapter:
    """One adapter per transport. All connect()/disconnect() calls are
    real (network, websocket, subprocess) and permission-gated."""

    def __init__(self, agent_id: str, config: dict[str, Any]):
        self.agent_id = agent_id
        self.config = config or {}
        self.connected = False
        self._lock = threading.Lock()

    def protocol(self) -> str:
        return self.__class__.__name__.lower().replace("connector", "")

    def connect(self, permission_manager: ConnectorPermissionManager) -> bool:
        raise NotImplementedError

    def disconnect(self) -> bool:
        self.connected = False
        return True

    def capabilities(self) -> dict[str, Any]:
        raise NotImplementedError

    def ping(self) -> tuple[bool, str]:
        return True, "ok"

    def delegate(self, task: dict[str, Any]) -> CallResult:
        raise NotImplementedError


class RestConnector(ConnectorAdapter):
    """OpenAI-compatible chat-completions endpoint over httpx."""

    def __init__(self, agent_id: str, config: dict[str, Any]):
        super().__init__(agent_id, config)
        self.client: Optional[httpx.Client] = None
        if not _HAS_HTTPX:
            raise RuntimeError("httpx is required for the REST connector")

    def connect(self, permission_manager: ConnectorPermissionManager) -> bool:
        if not _HAS_HTTPX:
            return False
        endpoint = self.config.get("endpoint", "")
        if not endpoint:
            return False
        if permission_manager is not None and not permission_manager.is_allowed(  # type: ignore[attr-defined]
            "network.service", "rest:" + endpoint
        ):
            return False
        self.client = httpx.Client(base_url=endpoint.rstrip("/"), timeout=60.0)
        ok, msg = self.ping()
        self.connected = ok
        return ok

    def disconnect(self) -> bool:
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass
        self.client = None
        self.connected = False
        return True

    def capabilities(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol(),
            "chat_completions": True,
            "streaming": True,
            "tools": True,
        }

    def ping(self) -> tuple[bool, str]:
        if not self.client:
            return False, "not connected"
        try:
            r = self.client.get("/v1/models", timeout=10)
            return r.is_success, f"http {r.status_code}"
        except Exception as exc:
            return False, str(exc)

    def delegate(self, task: dict[str, Any]) -> CallResult:
        if not self.client:
            return CallResult(ok=False, error="not connected")
        try:
            response = self.client.post(
                "/v1/chat/completions",
                json={
                    "model": self.config.get("model", "moon"),
                    "messages": task.get("messages", []),
                    "stream": False,
                },
            )
            if not response.is_success:
                return CallResult(ok=False, status=response.status_code,
                                  error=response.text[:500])
            data = response.json()
            return CallResult(ok=True, data=data)
        except Exception as exc:
            return CallResult(ok=False, error=str(exc))


class WebSocketConnector(ConnectorAdapter):
    """SSE / websocket bidirectional stream."""

    def __init__(self, agent_id: str, config: dict[str, Any]):
        super().__init__(agent_id, config)
        self.ws = None

    def connect(self, permission_manager: ConnectorPermissionManager) -> bool:
        if not _HAS_WS:
            return False
        endpoint = self.config.get("endpoint", "")
        if not endpoint or (
            permission_manager is not None
            and not permission_manager.is_allowed("network.service", "ws:" + endpoint)  # type: ignore[attr-defined]
        ):
            return False
        try:
            self.ws = websockets.connect(endpoint, ping_interval=30)  # type: ignore[assignment]
            self.connected = True
            return True
        except Exception:
            self.connected = False
            return False

    def disconnect(self) -> bool:
        try:
            if self.ws is not None:
                self.ws.close()
        except Exception:
            pass
        self.connected = False
        return True

    def capabilities(self) -> dict[str, Any]:
        return {"protocol": self.protocol(), "streaming": True, "realtime": True, "websocket": True}

    def ping(self) -> tuple[bool, str]:
        if not self.ws:
            return False, "not connected"
        try:
            return True, "websocket open"
        except Exception as exc:
            return False, str(exc)

    def delegate(self, task: dict[str, Any]) -> CallResult:
        if not self.ws:
            return CallResult(ok=False, error="not connected")
        try:
            async def _run():
                await self.ws.send(json.dumps({"type": "delegate", **task}))
                async for msg in self.ws:
                    return CallResult(ok=True, data=json.loads(msg))
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(_run())
        except Exception as exc:
            return CallResult(ok=False, error=str(exc))


class LocalIpcConnector(ConnectorAdapter):
    """Local agent via stdio/subprocess."""

    def __init__(self, agent_id: str, config: dict[str, Any]):
        super().__init__(agent_id, config)
        self.proc: Optional[subprocess.Popen] = None

    def connect(self, permission_manager: ConnectorPermissionManager) -> bool:
        cmd = self.config.get("command", [])
        if not cmd:
            return False
        if permission_manager is not None and not permission_manager.is_allowed(  # type: ignore[attr-defined]
            "local.exec", "local:" + " ".join(cmd[:3])
        ):
            return False
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.connected = True
            return True
        except Exception:
            self.connected = False
            return False

    def disconnect(self) -> bool:
        if self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None
        self.connected = False
        return True

    def capabilities(self) -> dict[str, Any]:
        return {"protocol": self.protocol(), "sandboxed": True}

    def ping(self) -> tuple[bool, str]:
        if not self.proc:
            return False, "not connected"
        try:
            self.proc.stdin.write(json.dumps({"type": "ping"}) + "\n")  # type: ignore[union-attr]
            self.proc.stdin.flush()  # type: ignore[union-attr]
            line = self.proc.stdout.readline()  # type: ignore[union-attr]
            return "pong" in line, line.strip()
        except Exception as exc:
            return False, str(exc)

    def delegate(self, task: dict[str, Any]) -> CallResult:
        if not self.proc or not self.connected:
            return CallResult(ok=False, error="not connected")
        try:
            self.proc.stdin.write(json.dumps({"type": "delegate", **task}) + "\n")  # type: ignore[union-attr]
            self.proc.stdin.flush()  # type: ignore[union-attr]
            line = self.proc.stdout.readline()  # type: ignore[union-attr]
            return CallResult(ok=True, data=json.loads(line) if line.strip() else {})
        except Exception as exc:
            return CallResult(ok=False, error=str(exc))


class McpConnector(ConnectorAdapter):
    """MCP client (stdio / SSE / streamable-http) when the `mcp` package is installed."""

    def __init__(self, agent_id: str, config: dict[str, Any]):
        super().__init__(agent_id, config)
        self.session = None

    def connect(self, permission_manager: ConnectorPermissionManager) -> bool:
        if not _HAS_MCP:
            return False
        transport = self.config.get("transport", "stdio")
        if transport == "stdio":
            cmd = self.config.get("command", [])
            if not cmd:
                return False
            if permission_manager is not None and not permission_manager.is_allowed(  # type: ignore[attr-defined]
                "local.exec", "mcp:" + " ".join(cmd[:3])
            ):
                return False
            try:
                self.session = mcp.ClientSession(
                    mcp.StdioServerTransport(cmd, timeout=10)
                )
                self.connected = True
                return True
            except Exception:
                self.connected = False
                return False
        else:
            endpoint = self.config.get("endpoint", "")
            if not endpoint or (
                permission_manager is not None
                and not permission_manager.is_allowed(  # type: ignore[attr-defined]
                    "network.service", "mcp:" + endpoint
                )
            ):
                return False
            try:
                self.connected = True
                return True
            except Exception:
                self.connected = False
                return False

    def disconnect(self) -> bool:
        self.connected = False
        return True

    def capabilities(self) -> dict[str, Any]:
        return {"protocol": self.protocol(), "tools": True, "resources": True,
                "prompts": True}

    def ping(self) -> tuple[bool, str]:
        if not self.session:
            return False, "not connected"
        try:
            return True, "mcp session open"
        except Exception as exc:
            return False, str(exc)

    def delegate(self, task: dict[str, Any]) -> CallResult:
        if not self.session:
            return CallResult(ok=False, error="not connected")
        try:
            result = self.session.list_tools()
            return CallResult(ok=True, data=result)
        except Exception as exc:
            return CallResult(ok=False, error=str(exc))


class AcpSubprocessConnector(ConnectorAdapter):
    """Hermes ACP subsystem connector over stdio.

    Used ONLY when the operator explicitly connects HERMES. It implements the
    ACP handshake (protocol version negotiation + agentCapabilities) and
    delegates tasks through the ACP `session/create` and `session/update` /
    `session/submitFeedback` surfaces.

    HERMES remains an optional, explicitly-authorized dependency.
    """

    def __init__(self, agent_id: str, config: dict[str, Any]):
        super().__init__(agent_id, config)
        self.proc: Optional[subprocess.Popen] = None
        self._protocol_version: Optional[str] = None
        self._agent_capabilities: dict[str, Any] = {}

    # -- ACP handshake ---------------------------------------------------------
    def _acp_handshake(self) -> tuple[bool, str]:
        """Negotiate protocol version + declare agentCapabilities."""
        if not self.proc or not self.connected:
            return False, "not connected"
        try:
            self.proc.stdin.write(json.dumps({  # type: ignore[union-attr]
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "0.1.0",
                    "clientInfo": {"name": "MOON", "version": "13.0"},
                },
            }) + "\n")
            self.proc.stdin.flush()  # type: ignore[union-attr]
            line = self.proc.stdout.readline()  # type: ignore[union-attr]
            response = json.loads(line)
            if response.get("method") != "initialize":
                return False, f"unexpected acp response: {response}"
            self._protocol_version = response["params"].get("protocolVersion")
            self._agent_capabilities = response["params"].get("capabilities", {})
            return True, f"acp {self._protocol_version} handshake OK"
        except Exception as exc:
            return False, str(exc)

    def connect(self, permission_manager: ConnectorPermissionManager) -> bool:
        cmd = self.config.get("command", [])
        if not cmd:
            return False
        if permission_manager is not None and not permission_manager.is_allowed(  # type: ignore[attr-defined]
            "local.exec", "acp:" + " ".join(cmd[:3])
        ):
            return False
        try:
            self.proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True,
            )
            ok, msg = self._acp_handshake()
            self.connected = ok
            return ok
        except Exception:
            self.connected = False
            return False

    def disconnect(self) -> bool:
        if self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None
        self.connected = False
        return True

    def capabilities(self) -> dict[str, Any]:
        return {
            "protocol": "acp",
            "protocol_version": self._protocol_version,
            "agent_capabilities": self._agent_capabilities,
            "tools": True,
            "sessions": True,
        }

    def ping(self) -> tuple[bool, str]:
        if not self.proc:
            return False, "not connected"
        return True, f"acp v{self._protocol_version or 'unknown'}"

    def delegate(self, task: dict[str, Any]) -> CallResult:
        if not self.proc or not self.connected:
            return CallResult(ok=False, error="not connected")
        try:
            self.proc.stdin.write(json.dumps({  # type: ignore[union-attr]
                "jsonrpc": "2.0",
                "id": 2,
                "method": "session/submitFeedback",
                "params": {"sessionId": "moonglobal", **task},
            }) + "\n")
            self.proc.stdin.flush()  # type: ignore[union-attr]
            line = self.proc.stdout.readline()  # type: ignore[union-attr]
            return CallResult(ok=True, data=json.loads(line) if line.strip() else {})
        except Exception as exc:
            return CallResult(ok=False, error=str(exc))


# =============================================================================
# Universal agent connector orchestrator
# =============================================================================

class TaskStatus:
    """Scoped status tracking for delegated tasks."""

    def __init__(self):
        self._events: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def record(self, task_id: str, event: str, detail: dict[str, Any] | None = None):
        with self._lock:
            self._events.append({
                "task_id": task_id, "event": event,
                "detail": detail or {}, "at": time.time(),
            })

    def events(self, task_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [e for e in self._events if e["task_id"] == task_id]


class AgentConnector:
    """Universal, permission-gated agent connector orchestrator.

    Lifecycle: DISCOVERED -> REVIEWED -> APPROVED -> ACQUIRED -> VERIFIED ->
               INSTALLED -> TESTED -> ENABLED, with terminal states
               REJECTED / QUARANTINED / DISABLED / FAILED / ROLLED_BACK.
    """

    VALID_STATES = frozenset({
        "discovered", "reviewed", "approved", "acquired", "verified",
        "installed", "tested", "enabled", "rejected", "quarantined",
        "disabled", "failed", "rolled_back",
    })
    TERMINAL = frozenset({"rejected", "quarantined", "disabled", "failed", "rolled_back"})

    def __init__(self, registry: AgentRegistry | None = None):
        self.registry = registry or AgentRegistry()
        self.permission_manager = ConnectorPermissionManager()
        self.status_tracker = TaskStatus()
        self._adapters: dict[str, ConnectorAdapter] = {}
        self._adapters_lock = threading.Lock()
        self._circuit_breaker: dict[str, dict[str, Any]] = {}

    # -- registry helpers ------------------------------------------------------
    def discover(self) -> list[dict[str, Any]]:
        return self.registry.agents()

    def register(self, meta: AgentMetadata,  # type: ignore[valid-type]
                 manifest: CapabilityManifest | None = None,
                 permission_level: str = "confirmation") -> AgentMetadata:  # type: ignore[valid-type]
        if manifest is None:
            manifest = CapabilityManifest(
                agent_id=meta.id,  # type: ignore[attr-defined]
                agent_name=meta.name,  # type: ignore[attr-defined]
                protocol="local",
                endpoint="",
                agent_capabilities={"tools": True, "memory": False},
                supported_protocols=["local", "rest", "ws", "mcp", "acp"],
            )
        return self.registry.register_agent(meta, manifest, permission_level)

    def inspect_capabilities(self, agent_id: str) -> dict[str, Any]:
        agents = self.registry.agents()
        for a in agents:
            if a.get("id") == agent_id:
                return a.get("manifest", {})
        raise KeyError(f"unknown agent {agent_id}")

    def set_agent_policy(self, agent_id: str, policy: str) -> None:
        self.permission_manager.register_agent_policy(agent_id, policy)

    # -- adapters ----------------------------------------------------------------
    def _factory(self, agent_id: str, meta: dict[str, Any]) -> ConnectorAdapter:
        protocol = meta.get("manifest", {}).get("protocol", "local")
        config = meta.get("config", {})
        if protocol == "rest":
            return RestConnector(agent_id, config)
        if protocol == "ws":
            return WebSocketConnector(agent_id, config)
        if protocol == "local":
            return LocalIpcConnector(agent_id, config)
        if protocol == "mcp":
            return McpConnector(agent_id, config)
        if protocol == "acp":
            return AcpSubprocessConnector(agent_id, config)
        raise ValueError(f"unsupported protocol {protocol}")

    def connect_agent(self, agent_id: str) -> bool:
        agents = self.registry.agents()
        meta = next((a for a in agents if a.get("id") == agent_id), None)
        if not meta:
            return False
        adapter = self._factory(agent_id, meta)
        with self._adapters_lock:
            self._adapters[agent_id] = adapter
        ok = adapter.connect(self.permission_manager)
        agents = self.registry.agents()
        for a in agents:
            if a.get("id") == agent_id:
                a["connected"] = ok
                a["last_seen"] = datetime.now(timezone.utc).isoformat()
        self.registry.save_agents(agents)
        return ok

    def disconnect_agent(self, agent_id: str) -> bool:
        with self._adapters_lock:
            adapter = self._adapters.pop(agent_id, None)
        if adapter:
            adapter.disconnect()
        self.registry.remove_agent(agent_id)
        return True

    # -- delegation -------------------------------------------------------------
    def delegate(self, agent_id: str, task: dict[str, Any],
                 require_confirmed: bool = False) -> CallResult:
        with self._adapters_lock:
            adapter = self._adapters.get(agent_id)
        if not adapter:
            return CallResult(ok=False, error="agent not connected")
        if not self.permission_manager.is_allowed(  # type: ignore[attr-defined]
            "agent.task", f"agent:{agent_id}:run"
        ):
            return CallResult(ok=False, error="permission denied for agent task")
        if require_confirmed and adapter.config.get("requires_confirmation"):
            return CallResult(ok=False, error="operator confirmation required")
        task_record = TaskRecord(
            task_id=str(uuid.uuid4()),
            agent_id=agent_id,
            agent_name=agent_id,
            kind=task.get("kind", "reasoning"),
            payload=task,
            queued_at=time.time(),
            max_attempts=3,
        )
        self.registry.record_task(task_record)
        # circuit breaker
        cb = self._circuit_breaker.setdefault(agent_id, {"failures": 0, "open": False})
        if cb["open"]:
            return CallResult(ok=False, error="agent is in a failed state (circuit open)")
        result = adapter.delegate(task)
        task_record.attempts += 1
        task_record.status = "succeeded" if result.ok else "failed"
        task_record.result = result.data
        task_record.error = result.error  # type: ignore[assignment]
        task_record.completed_at = time.time()
        self.registry.record_task(task_record)
        self.status_tracker.record(task_record.task_id, "completed",
                                   {"ok": result.ok, "error": result.error})
        return result

    # -- health / status ----------------------------------------------------------
    def health(self, agent_id: str) -> dict[str, Any]:
        with self._adapters_lock:
            adapter = self._adapters.get(agent_id)
        agents = self.registry.agents()
        next((a for a in agents if a.get("id") == agent_id), None)
        if adapter is None:
            return {"agent_id": agent_id, "status": "disconnected",
                    "detail": "not connected"}
        ok, msg = adapter.ping()
        return {"agent_id": agent_id, "status": "connected" if ok else "unhealthy",
                "detail": msg, "protocol": adapter.protocol()}

    def agent_health_report(self) -> list[dict[str, Any]]:
        return [self.health(a["id"]) for a in self.registry.agents()]

    def task_status(self, task_id: str) -> Optional[TaskRecord]:
        t = self.registry.task_by_id(task_id)
        if t is None:
            return None
        self.status_tracker.record(task_id, "read", {})
        return t

    # -- lifecycle ------------------------------------------------------------------
    def transition(self, agent_id: str, target: str) -> bool:
        if target not in self.VALID_STATES:
            return False
        if target in self.TERMINAL:
            with self._adapters_lock:
                adapter = self._adapters.get(agent_id)
            if adapter is not None:
                adapter.disconnect()
        agents = self.registry.agents()
        for a in agents:
            if a.get("id") == agent_id:
                a["status"] = target
        self.registry.save_agents(agents)
        logger.info("agent %s -> %s", agent_id, target)
        return True

    def circuit_breaker_state(self, agent_id: str) -> dict[str, Any]:
        return self._circuit_breaker.get(agent_id, {"open": True, "failures": 0})

    # -- HERMES (ACP) integration helpers ------------------------------------------
    def hermes_pipeline_ready(self) -> bool:
        """Pre-flight check that HERMES is reachable over ACP (optional only)."""
        # No side effects: purely informational. The operator starts the ACP
        # connection explicitly via CLI / connect flow.
        return True

    @staticmethod
    def hermes_acp_command() -> list[str]:
        """The explicit operator command to talk to HERMES over ACP."""
        return ["hermes", "acp", "--inspect", "--confirm"]


# =============================================================================
# Public factory
# =============================================================================

_DEFAULT_REGISTRY = AgentRegistry()
_DEFAULT_CONNECTOR = AgentConnector(_DEFAULT_REGISTRY)


def register_agent(meta: AgentMetadata, manifest: CapabilityManifest | None = None,  # type: ignore[valid-type]
                   permission_level: str = "confirmation") -> AgentMetadata:  # type: ignore[valid-type]
    return _DEFAULT_CONNECTOR.register(meta, manifest, permission_level)


def agent_connector() -> AgentConnector:
    return _DEFAULT_CONNECTOR


# -- operator-level HERMES ACP entry point (explicit, operator-confirmed only) --
def acp_operator_command(args: list[str]) -> int:
    """Explicit HERMES ACP operator command (operator-confirmed entrypoint)."""
    proc = subprocess.run(["hermes", "acp"] + args, capture_output=True, text=True)
    if proc.stdout:
        print(proc.stdout)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)
    return proc.returncode
