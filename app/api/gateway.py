"""Gateway API surface -- REST + WebSocket gateway for MOON-AI's connection layer.

Everything the agent-facing :class:`GlobalConnectorTool` exposes, over HTTP, so
CYCLONE and queriers can call the gateway without an agent session. Supports
connect, list, call, health, status, task submission/result polling, check,
mute, unmute and disconnect for service/agent/mcp/webhook/websocket connections.

A single **ConnectionGateway** is shared with the tool layer (built in
:meth:`get_gateway`) so the API and the tool layer mutate the same
``connections/registry.json`` -- never two copies.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.connector.gateway import (
    ConnectionGateway,
    ConnectionRecord,
    get_shared_connection_gateway,
)
from app.connector.manifest import ManifestValidationError, validate_agent_manifest

TERMINAL_TOKEN = ""


def _token_ok(ws_or_headers):  # noqa: F811
    return bool(TERMINAL_TOKEN)


logger = logging.getLogger(__name__)

# ---- one shared gateway; the tool layer and this router point at it ----------
_gateway: ConnectionGateway | None = None


def get_gateway() -> ConnectionGateway:
    """Return the (singleton) ConnectionGateway shared with the tool layer."""
    global _gateway
    if _gateway is None:
        _gateway = get_shared_connection_gateway()
    return _gateway


def get_gateway_router() -> APIRouter:
    """Build the gateway router with every endpoint bound to real state."""
    router = APIRouter(prefix="/gateway", tags=["gateway"])
    gw = get_gateway()

    def _auth_ok(headers: dict | None) -> bool:
        return not TERMINAL_TOKEN or _token_ok(headers or {})

    def _operator_confirmed(headers: dict, supplied: object) -> bool:
        return (
            supplied is True
            and bool(TERMINAL_TOKEN)
            and _token_ok(headers)
        )

    # -- lifecycle -----------------------------------------------------------
    @router.get("/health")
    async def gateway_health(request: Request):
        if not _auth_ok(dict(request.headers)):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        conns = gw.list()
        return JSONResponse({"ok": True, "count": len(conns),
                             "connections": [c.to_dict() for c in conns]})

    @router.get("/connections")
    async def list_connections(request: Request):
        if not _auth_ok(dict(request.headers)):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        conns = gw.list()
        return JSONResponse({"connections": [c.to_dict() for c in conns],
                             "count": len(conns)})

    @router.post("/connections")
    async def register_connection(request: Request):
        if not _auth_ok(dict(request.headers)):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        name = str(body.get("name") or "")
        url = str(body.get("url") or "")
        kind = str(body.get("kind") or "service").lower()
        if not name or not url:
            return JSONResponse({"error": "connect requires name and url"},
                                status_code=400)
        manifest = body.get("manifest")
        if manifest is not None:
            if kind != "agent":
                return JSONResponse(
                    {"error": "only agent connections may declare a manifest"},
                    status_code=400,
                )
            try:
                manifest = validate_agent_manifest(manifest)
            except ManifestValidationError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
        rec = ConnectionRecord(
            name=name, kind=kind, url=url,
            model=str(body.get("model", "")),
            scope=str(body.get("scope", "network.egress")),
            permissions=list(body.get("permissions", [])),
            credential_ref=str(body.get("credential_ref", "")),
            enabled=bool(body.get("enabled", True)),
            manifest=manifest,
        )
        allowed, tier, reason = gw.authorize_egress(
            rec.url,
            rec.scope,
            confirmed=_operator_confirmed(dict(request.headers), body.get("confirmed")),
        )
        if not allowed:
            return JSONResponse(
                {
                    "error": reason,
                    "confirmation_required": tier == "confirmation",
                },
                status_code=403,
            )
        try:
            gw.register(rec)
        except ManifestValidationError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse({"name": rec.name, "kind": rec.kind, "url": rec.url,
                             "status": rec.last_status}, status_code=201)

    @router.get("/connections/{conn_id}")
    async def get_connection(request: Request, conn_id: str):
        if not _auth_ok(dict(request.headers)):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        rec = gw.get(conn_id)
        if rec is None:
            return JSONResponse({"error": f"no connection named '{conn_id}'"},
                                status_code=404)
        return JSONResponse(rec.to_dict())

    @router.delete("/connections/{conn_id}")
    async def disconnect_connection(request: Request, conn_id: str):
        if not _auth_ok(dict(request.headers)):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        if not isinstance(body, dict) or not _operator_confirmed(
            dict(request.headers), body.get("confirmed")
        ):
            return JSONResponse(
                {"error": "operator confirmation required to disconnect this connection"},
                status_code=403,
            )
        if gw.remove(conn_id):
            return JSONResponse({"name": conn_id, "removed": True})
        return JSONResponse({"error": f"no connection named '{conn_id}'"},
                            status_code=404)

    @router.post("/connections/{conn_id}/disconnect")
    async def alias_disconnect_connection(request: Request, conn_id: str):
        # Convenience alias for DELETE /connections/{id}
        return await disconnect_connection(request, conn_id)

    @router.post("/connections/{conn_id}/status")
    async def set_connection_status(request: Request, conn_id: str):
        if not _auth_ok(dict(request.headers)):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        status = str(body.get("status") or "unknown")
        gw.set_status(conn_id, status)
        return JSONResponse({"name": conn_id, "status": gw.get(conn_id).last_status
                             if gw.get(conn_id) else None})

    @router.post("/connections/{conn_id}/check")
    async def check_connection(request: Request, conn_id: str):
        """Probe a single connection and record its real status."""
        if not _auth_ok(dict(request.headers)):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        rec = gw.get(conn_id)
        if rec is None:
            return JSONResponse({"error": f"no connection named '{conn_id}'"},
                                status_code=404)
        if not rec.enabled:
            return JSONResponse({"error": f"connection '{conn_id}' is disabled"},
                                status_code=409)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        allowed, tier, reason = gw.authorize_egress(
            rec.url,
            rec.scope,
            confirmed=_operator_confirmed(dict(request.headers), body.get("confirmed")),
        )
        if not allowed:
            return JSONResponse(
                {
                    "error": reason,
                    "confirmation_required": tier == "confirmation",
                },
                status_code=403,
            )
        conn = gw.build_connector(rec)
        try:
            if rec.kind == "agent":
                res = await conn.ask("__gateway_check__",
                                     system="gateway status probe")
            elif rec.kind == "websocket":
                res = await conn.send_recv("__gateway_check__")
            elif rec.kind == "mcp":
                c_res = await conn.connect()
                if not c_res.ok:
                    res = c_res
                else:
                    try:
                        res = await conn.list_tools()
                    finally:
                        await conn.close()
            else:
                res = await conn.call("GET", "/")
            gw.set_status(conn_id, "ok" if res.ok else f"error:{res.error or res.status}")
            detail = (res.data if isinstance(res.data, str)
                      else json.dumps(res.data, default=str)[:160])
            return JSONResponse({"name": conn_id, "ok": res.ok,
                                 "detail": detail, "status": gw.get(conn_id).last_status})
        except Exception as exc:  # noqa: BLE001
            gw.set_status(conn_id, f"error:{exc}")
            return JSONResponse({"name": conn_id, "ok": False,
                                 "detail": str(exc)[:160],
                                 "status": f"error:{exc}"})

    @router.post("/connections/{conn_id}/discover")
    async def discover_connection_manifest(request: Request, conn_id: str):
        if not _auth_ok(dict(request.headers)):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        if not isinstance(body, dict):
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        result = await gw.discover_agent_manifest(
            conn_id,
            confirmed=_operator_confirmed(
                dict(request.headers), body.get("confirmed")
            ),
        )
        if result.get("ok"):
            return JSONResponse(result)
        if result.get("confirmation_required"):
            return JSONResponse(result, status_code=403)
        if result.get("error", "").startswith("no connection named"):
            return JSONResponse(result, status_code=404)
        if result.get("error", "").startswith("connection '"):
            return JSONResponse(result, status_code=409)
        return JSONResponse(result, status_code=502)

    @router.post("/connections/{conn_id}/tasks")
    async def submit_agent_task(request: Request, conn_id: str):
        if not _auth_ok(dict(request.headers)):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        result = await gw.submit_agent_task(
            conn_id,
            body.get("message"),
            system=body.get("system", ""),
            confirmed=_operator_confirmed(
                dict(request.headers), body.get("confirmed")
            ),
            capability=body.get("capability", ""),
            input_data=body.get("input"),
        )
        if result.get("ok"):
            return JSONResponse(result, status_code=202)
        if result.get("confirmation_required"):
            return JSONResponse(result, status_code=403)
        if result.get("error", "").startswith("no connection named"):
            return JSONResponse(result, status_code=404)
        if result.get("error", "").startswith("connection '"):
            return JSONResponse(result, status_code=409)
        if result.get("error") == "agent task queue is full":
            return JSONResponse(result, status_code=429)
        return JSONResponse(result, status_code=400)

    @router.get("/tasks/{task_id}")
    async def get_agent_task(request: Request, task_id: str):
        if not _auth_ok(dict(request.headers)):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        task = gw.get_agent_task(task_id)
        if task is None:
            return JSONResponse({"error": "agent task not found"}, status_code=404)
        return JSONResponse(task)

    @router.post("/connections/{conn_id}/mute")
    async def mute_connection(request: Request, conn_id: str):
        if not _auth_ok(dict(request.headers)):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        if gw.set_enabled(conn_id, False):
            return JSONResponse({"name": conn_id, "enabled": False})
        return JSONResponse({"error": f"no connection named '{conn_id}'"},
                            status_code=404)

    @router.post("/connections/{conn_id}/unmute")
    async def unmute_connection(request: Request, conn_id: str):
        if not _auth_ok(dict(request.headers)):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        if gw.set_enabled(conn_id, True):
            return JSONResponse({"name": conn_id, "enabled": True})
        return JSONResponse({"error": f"no connection named '{conn_id}'"},
                            status_code=404)

    return router
