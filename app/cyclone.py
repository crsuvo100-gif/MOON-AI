"""Real Cyclone bridge for MOON-AI.

Reuse the existing CYCLONE_TERMINAL_AI_V10/ source tree instead of shipping a
fabricated ``cyclone`` package.  MOON-AI serves CYCLONE's browser UI and
proxies CYCLONE's own HTTP API (/api/*) through MOON-AI's FastAPI app, so the
CYCLONE terminal is fully reachable through MOON-AI's browser and command
surfaces while every CYCLONE request still lands on the real Node.js server.

Public surface (matches the original bridge contract):
    get_cyclone_router()      -> APIRouter: proxy for CYCLONE's /api/*
    get_cyclone_static_files()-> StaticFiles: CYCLONE's browser UI tree
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Awaitable, Callable

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

_CYCLONE_DIR: Path | None = None
_CYCLONE_HOST = os.environ.get("CYCLONE_HOST", "127.0.0.1")
_CYCLONE_PORT = int(os.environ.get("CYCLONE_PORT", "8765"))
_CYCLONE_BASE = f"http://{_CYCLONE_HOST}:{_CYCLONE_PORT}"

# Methods CYCLONE's API accepts.  OPTIONS is used for CORS preflight.
_ALLOWED_METHODS = ["GET", "HEAD", "POST", "PUT", "DELETE", "OPTIONS"]

# Hop-by-hop headers that must never be forwarded into a proxied request.
_DROP_HEADERS = {
    "host",
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "content-length",
}

# Client reused for every proxied CYCLONE API call.  It is created lazily so
# that tests that restart the event loop (FastAPI TestClient) can still use it:
# as soon as a closed instance is detected, a fresh transport is opened.
_client = httpx.AsyncClient(timeout=90.0)


def _resolve_cyclone_dir() -> Path:
    """Locate the existing CYCLONE source tree (never fabricate one)."""
    global _CYCLONE_DIR
    if _CYCLONE_DIR is not None:
        return _CYCLONE_DIR
    here = Path(__file__).resolve().parent.parent  # <MOON>/
    candidates = (
        here / "CYCLONE_TERMINAL_AI_V10",
        here / "MOON-AI" / "CYCLONE_TERMINAL_AI_V10",
        Path.cwd() / "CYCLONE_TERMINAL_AI_V10",
    )
    for candidate in candidates:
        if candidate.is_dir():
            _CYCLONE_DIR = candidate
            return _CYCLONE_DIR
    raise RuntimeError(
        "CYCLONE_TERMINAL_AI_V10 source tree not found next to the MOON project"
    )


def get_cyclone_static_files():
    """Serve CYCLONE's browser UI from the existing source tree."""
    return StaticFiles(directory=str(_resolve_cyclone_dir()), html=True)


def get_cyclone_router() -> APIRouter:
    """Return a router that proxies CYCLONE's /api/* to the real Node.js server."""
    router = APIRouter()

    @router.api_route("/api/{full_path:path}", methods=_ALLOWED_METHODS)
    async def _cyclone_api(request: Request, full_path: str):
        # full_path is the remainder after MOON-AI's "/cyclone/api" mount, e.g.
        # "health" from "/cyclone/api/health". Cyclone's own apiBase is /api, so
        # prepend it — do not strip and re-prepend (which produced
        # "http://127.0.0.1:8765/providers" instead of "/api/providers").
        url = f"{_CYCLONE_BASE}/api/{full_path}" if full_path else f"{_CYCLONE_BASE}/api"

        body = None
        if request.method in {"POST", "PUT", "DELETE", "PATCH"}:
            body = await request.body()

        # Only forward the headers CYCLONE's server will actually honour.
        headers = {}
        for key, value in request.headers.items():
            lowered = key.lower()
            if lowered in _DROP_HEADERS:
                continue
            # Keep the request identifiable to CYCLONE's rate limiter.
            if lowered in {"user-agent", "x-forwarded-for", "x-real-ip"}:
                headers[key] = value
            else:
                headers[key] = value

        # The real CYCLONE server is the only origin this router ever speaks to.
        # A fresh transport per request is used (cheap for a terminal bridge) so
        # the proxy is independent of any module-level client lifecycle.
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.request(
                method=request.method,
                url=url,
                content=body,
                headers=headers,
                follow_redirects=False,
            )

        # Return the real CYCLONE payload; do not fabricate HTTP status codes.
        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=response.headers,
            media_type=response.headers.get("content-type", "application/json"),
        )

    return router
