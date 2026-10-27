"""Gateway API surface -- REST + WebSocket gateway for MOON-AI's connection layer.

Everything the agent-facing :class:`GlobalConnectorTool` exposes, over HTTP, so
CYCLONE and queriers can call the gateway without an agent session. Supports
connect, list, call, health, status, check, mute, unmute and disconnect for
service/agent/mcp/webhook/websocket connections.

A single **ConnectionGateway** is shared with the tool layer (built in
:meth:`get_gateway`) so the API and the tool layer mutate the same
``connections/registry.json`` -- never two copies.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.connector.gateway import ConnectionGateway, ConnectionRecord

try:  # same gate as every /api endpoint
    from app.terminal_interface import TERMINAL_TOKEN, _token_ok
except Exception:  # pragma: no cover - fallback guard
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
        from app.connector.gateway import ConnectionGateway
        _gateway = ConnectionGateway()
    return _gateway


def get_gateway_router() -> APIRouter:
    """Build the gateway router with every endpoint bound to real state."""
    router = APIRouter(prefix="/gateway", tags=["gateway"])
    gw = get_gateway()

    def _auth_ok(headers: dict | None) -> bool:
        return not TERMINAL_TOKEN or _token_ok(headers or {})

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
        rec = ConnectionRecord(
            name=name, kind=kind, url=url,
            model=str(body.get("model", "")),
            scope=str(body.get("scope", "network.egress")),
            permissions=list(body.get("permissions", [])),
            credential_ref=str(body.get("credential_ref", "")),
            enabled=bool(body.get("enabled", True)),
        )
        gw.register(rec)
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
        conn = gw.build_connector(rec)
        try:
            if rec.kind == "agent":
                res = await conn.ask("__gateway_check__",
                                     system="gateway status probe")
            elif rec.kind == "websocket":
                res = await conn.send_recv("__gateway_check__")
            elif rec.kind == "mcp":
                # Establish the transport before probing. Previously this branch
                # called conn._call("list_tools") directly, which returned
                # "MCP transport not connected; call connect() first" whenever
                # connect() was never invoked -- so every MCP connection looked
                # permanently disconnected. Now we connect first; if the transport
                # fails to open, surface that real error instead of a stale one.
                c_res = await conn.connect()
                res = await conn._call("list_tools")
                if not res.ok:
                    res = c_res if not c_res.ok else res
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
