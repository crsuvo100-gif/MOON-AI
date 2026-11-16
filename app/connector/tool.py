"""GlobalConnectorTool -- MOON-AI's agent-facing global-connection tool.

ADDITIVE: exposes the ConnectionGateway to MOON-AI's tool layer. Logical actions:
  connect   -- register a new connection (service/agent/mcp/webhook/ws)
  list      -- show registered connections + permission posture
  call      -- invoke an HTTP/agent connection (permission-checked)
  health    -- ping every connection and record real status
  disconnect-- remove a connection

Every state-changing/egress action is permission-gated. CONFIRMATION-tier hosts
require the operator to pass `confirmed=true`. NEVER-tier (credential reads) is
always denied. Nothing egresses without a passing gate -- no fake telemetry.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.connector.gateway import (
    ConnectionGateway,
    ConnectionRecord,
    get_shared_connection_gateway,
)
from app.connector.manifest import ManifestValidationError, validate_agent_manifest
from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


class GlobalConnectorTool(BaseTool):
    name = "global_connector"
    description = (
        "MOON-AI's global connection layer. Register and call connections to external "
        "services, other AI agents, MCP tool-servers, webhooks, and websockets -- "
        "all permission-gated. Actions: connect, list, inspect, discover, call, health, "
        "disconnect, federate, submit, task_status."
    )

    def __init__(self, gateway: ConnectionGateway | None = None) -> None:
        self._gw = gateway or get_shared_connection_gateway()

    async def execute(self, **kwargs: Any) -> Any:
        action = (kwargs.get("action") or "list").lower()
        if action == "connect":
            return await self._connect(kwargs)
        if action == "list":
            return self._list()
        if action == "inspect":
            return self._inspect(kwargs)
        if action == "discover":
            return await self._discover(kwargs)
        if action == "call":
            return await self._call(kwargs)
        if action == "health":
            return await self._health(kwargs)
        if action == "disconnect":
            return self._disconnect(kwargs)
        if action == "federate":
            return await self._federate(kwargs)
        if action == "submit":
            return await self._submit(kwargs)
        if action == "task_status":
            return self._task_status(kwargs)
        return (
            f"[global_connector] unknown action '{action}'. "
            "Use connect|list|inspect|discover|call|health|disconnect|federate|submit|task_status."
        )

    # -- actions ------------------------------------------------------------
    async def _connect(self, kw: dict) -> str:
        name = kw.get("name") or ""
        url = kw.get("url") or ""
        kind = (kw.get("kind") or "service").lower()
        if not name or not url:
            return "[global_connector] connect requires name and url."
        manifest = kw.get("manifest")
        if manifest is not None:
            if kind != "agent":
                return "[global_connector] only agent connections may declare a manifest."
            try:
                manifest = validate_agent_manifest(manifest)
            except ManifestValidationError as exc:
                return f"[global_connector] invalid agent manifest: {exc}"
        host = self._gw.host_of(url)
        scope = {
            "agent": "network.agent", "service": "network.service",
            "webhook": "network.webhook", "mcp": "network.service",
            "websocket": "network.service",
        }.get(kind, "network.egress")
        allowed, tier, reason = self._gw.authorize_egress(
            url, scope, confirmed=kw.get("confirmed") is True
        )
        if not allowed and tier == "never":
            return f"[global_connector] BLOCKED: {reason}"
        if not allowed and tier == "confirmation" and not kw.get("confirmed"):
            return (f"[global_connector] OPERATOR CONFIRMATION REQUIRED to connect to '{host}' "
                    f"({reason}). Model-provided confirmation is not sufficient; configure "
                    "ALLOWED_EGRESS_HOSTS or use a trusted approval path.")
        rec = ConnectionRecord(
            name=name, kind=kind, url=url, model=kw.get("model", ""),
            scope=scope, permissions=(scope,), credential_ref=kw.get("credential_ref", ""),
            manifest=manifest,
        )
        try:
            self._gw.register(rec)
        except ManifestValidationError as exc:
            return f"[global_connector] invalid agent manifest: {exc}"
        return (f"[global_connector] registered '{name}' ({kind}) -> {url}\n"
                f"  egress tier: {tier} | reason: {reason}\n"
                f"  secrets are referenced by name only; never stored on disk.")

    def _list(self) -> str:
        conns = self._gw.list()
        if not conns:
            return "[global_connector] no connections registered yet."
        lines = ["[global_connector] registered connections:"]
        for c in conns:
            lines.append(f"  - {c.name} [{c.kind}] {c.url}  status={c.last_status}")
        lines.append(
            "\nEgress is permission-gated: explicitly allowlisted hosts are SAFE; "
            "all other destinations, including loopback/private hosts, require "
            "operator confirmation. Model-generated confirmation is not trusted."
        )
        return "\n".join(lines)

    def _inspect(self, kw: dict) -> str:
        name = kw.get("name") or ""
        if not name:
            return "[global_connector] inspect requires a connection name."
        record = self._gw.get(name)
        if record is None:
            return f"[global_connector] no connection named '{name}'."
        if record.kind != "agent":
            return f"[global_connector] '{name}' is not an agent connection."
        if record.manifest is None:
            return (
                f"[global_connector] '{name}' has no declared capability manifest; "
                "the endpoint has not been queried."
            )
        return (
            "[global_connector] declared agent manifest (peer claims; not independently verified):\n"
            + json.dumps(record.manifest, ensure_ascii=False, sort_keys=True)
        )

    async def _discover(self, kw: dict) -> str:
        name = kw.get("name") or ""
        if not name:
            return "[global_connector] discover requires an agent connection name."
        result = await self._gw.discover_agent_manifest(
            name, confirmed=kw.get("confirmed") is True
        )
        if not result.get("ok"):
            return f"[global_connector] {result.get('error', 'manifest discovery failed')}"
        return (
            f"[global_connector] discovered manifest for '{name}' "
            "(peer claims; not independently verified):\n"
            + json.dumps(result["manifest"], ensure_ascii=False, sort_keys=True)
        )

    async def _call(self, kw: dict) -> str:
        name = kw.get("name") or ""
        rec = self._gw.get(name)
        if rec is None:
            return f"[global_connector] no connection named '{name}'."
        if not rec.enabled:
            return f"[global_connector] '{name}' is disabled."
        host = self._gw.host_of(rec.url)
        allowed, tier, reason = self._gw.authorize_egress(
            rec.url, rec.scope, confirmed=kw.get("confirmed") is True
        )
        if not allowed and tier == "never":
            return f"[global_connector] BLOCKED: {reason}"
        if not allowed and tier == "confirmation" and not kw.get("confirmed"):
            return (f"[global_connector] OPERATOR CONFIRMATION REQUIRED to call '{host}' "
                    f"({reason}). Model-provided confirmation is not sufficient; configure "
                    "ALLOWED_EGRESS_HOSTS or use a trusted approval path.")
        conn = self._gw.build_connector(rec)
        try:

            if rec.kind == "agent":
                res = await conn.ask(kw.get("message", ""), system=kw.get("system", ""))
            elif rec.kind == "websocket":
                # REAL websocket: open and send a message (was a no-op health() call).
                res = await conn.send_recv(kw.get("message", ""))
            elif rec.kind == "mcp":
                mcp_method = (kw.get("method") or "list_tools").lower()
                if mcp_method not in conn._CALLABLE_METHODS:
                    return f"[global_connector] unsupported MCP method '{mcp_method}'."
                mcp_params: dict[str, Any] = {}
                if mcp_method == "call_tool":
                    tool_name = kw.get("tool")
                    if not tool_name:
                        return "[global_connector] MCP call_tool requires a tool name."
                    mcp_params["name"] = tool_name
                    mcp_params["arguments"] = kw.get("arguments") or {}
                else:
                    mcp_params = {k: v for k, v in kw.items()
                                  if k not in ("method", "message", "confirmed")}
                connected = await conn.connect()
                if not connected.ok:
                    res = connected
                else:
                    try:
                        res = await conn._call(mcp_method, **mcp_params)
                    finally:
                        await conn.close()
            else:
                method = (kw.get("method") or "GET").upper()
                res = await conn.call(method, kw.get("path", ""), json_body=kw.get("json"),
                                      params=kw.get("params"), data=kw.get("data"))
        except Exception as exc:  # noqa: BLE001
            self._gw.set_status(name, f"error:{exc}")
            return f"[global_connector] call failed: {exc}"
        self._gw.set_status(name, "ok" if res.ok else f"http:{res.status}")
        body = res.data if isinstance(res.data, str) else json.dumps(res.data, default=str)[:1500]
        return f"[global_connector] {name} -> {res.status}\n{body}"

    async def _health(self, kw: dict) -> str:
        lines = ["[global_connector] connection health:"]
        for c in self._gw.list():
            allowed, tier, reason = self._gw.authorize_egress(
                c.url, c.scope, confirmed=kw.get("confirmed") is True
            )
            if not allowed:
                status = "BLOCKED" if tier == "never" else "CONFIRMATION REQUIRED"
                lines.append(f"  - {c.name} [{c.kind}] {status} :: {reason}")
                continue
            conn = self._gw.build_connector(c)
            try:
                res = await conn.health()
                ok = res.ok
                detail = (res.data if isinstance(res.data, str) else json.dumps(res.data, default=str))[:120]
            except Exception as exc:  # noqa: BLE001
                ok, detail = False, str(exc)[:120]
            self._gw.set_status(c.name, "ok" if ok else "unreachable")
            lines.append(f"  - {c.name} [{c.kind}] {'ONLINE' if ok else 'UNREACHABLE'} :: {detail}")
        return "\n".join(lines)

    def _disconnect(self, kw: dict) -> str:
        name = kw.get("name") or ""
        if not name:
            return "[global_connector] disconnect requires a connection name."
        if kw.get("operator_confirmed") is not True:
            return (
                f"[global_connector] OPERATOR CONFIRMATION REQUIRED to disconnect '{name}'."
            )
        if self._gw.remove(name):
            return f"[global_connector] removed '{name}'."
        return f"[global_connector] no connection named '{name}'."

    async def _federate(self, kw: dict) -> str:
        """Delegate a prompt to a registered peer AI agent; two-way federation.

        Reuses the gateway's permission-gated call_agent(); folds the peer's
        answer back as MOON-AI's own result. This is how MOON-AI 'connects to any AI
        agent' and collaborates rather than just firing one-shot HTTP.
        """
        name = kw.get("name") or ""
        message = kw.get("message") or ""
        if not name or not message:
            return "[global_connector] federate requires name (peer agent) and message."
        res = await self._gw.call_agent(
            name,
            message,
            system=kw.get("system", ""),
            confirmed=kw.get("confirmed") is True,
        )
        if not res.get("ok"):
            return f"[global_connector] federation with '{name}' failed: {res.get('error')}"
        return (f"[global_connector] '{name}' (peer {res.get('agent')}) replied:\n"
                f"{res.get('answer')}")

    async def _submit(self, kw: dict) -> str:
        name = kw.get("name") or ""
        message = kw.get("message")
        if not name or not isinstance(message, str):
            return "[global_connector] submit requires an agent name and task message."
        result = await self._gw.submit_agent_task(
            name,
            message if isinstance(message, str) else "",
            system=kw.get("system", ""),
            confirmed=kw.get("confirmed") is True,
            capability=kw.get("capability", ""),
            input_data=kw.get("input"),
        )
        return "[global_connector] " + json.dumps(result, ensure_ascii=False, sort_keys=True)

    def _task_status(self, kw: dict) -> str:
        task_id = kw.get("task_id") or ""
        if not isinstance(task_id, str) or not task_id:
            return "[global_connector] task_status requires a task_id."
        task = self._gw.get_agent_task(task_id)
        if task is None:
            return f"[global_connector] no agent task named '{task_id}'."
        return "[global_connector] " + json.dumps(task, ensure_ascii=False, sort_keys=True)
