"""Concrete connector clients -- real, working network bridges.

Each connector performs an ACTUAL outbound call (httpx / websocket / MCP) and
returns structured CallResult. Permission checks live in the ConnectionGateway
BEFORE any connector is invoked. No fake telemetry.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class CallResult:
    ok: bool
    status: int = 0
    data: Any = None
    error: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


class HTTPConnector:
    """Call an external REST/HTTP service."""

    def __init__(self, base_url: str, headers: dict[str, str] | None = None,
                 timeout: float = 30.0) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {**(headers or {}), "User-Agent": "MOON-AI-Connector/1.0"}
        self._to = timeout

    async def call(self, method: str, path: str = "", *, json_body: Any = None,
                   params: dict | None = None, data: Any = None) -> CallResult:
        url = f"{self._base}/{path.lstrip('/')}" if path else self._base
        try:
            async with httpx.AsyncClient(timeout=self._to, headers=self._headers) as c:
                r = await c.request(method.upper(), url, json=json_body, params=params, data=data)
                try:
                    body = r.json()
                except Exception:
                    body = r.text
                return CallResult(ok=r.is_success, status=r.status_code, data=body,
                                  headers=dict(r.headers))
        except Exception as exc:  # noqa: BLE001
            return CallResult(ok=False, status=0, error=str(exc))

    async def health(self) -> CallResult:
        return await self.call("GET", "")


class AgentConnector:
    """Talk to ANOTHER AI agent via an OpenAI-compatible chat endpoint.

    Lets MOON-AI federate: send a prompt to a peer agent, get its answer back.
    This is the "connect to any AI agent" path.
    """

    def __init__(self, base_url: str, model: str, api_key: str = "not-required",
                 timeout: float = 120.0) -> None:
        self._base = base_url.rstrip("/")
        self._model = model
        self._key = api_key
        self._to = timeout

    async def ask(self, message: str, *, system: str = "",
                  history: list[dict] | None = None) -> CallResult:
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        for m in (history or []):
            msgs.append(m)
        msgs.append({"role": "user", "content": message})
        payload = {"model": self._model, "messages": msgs, "temperature": 0.7, "max_tokens": 2048}
        try:
            async with httpx.AsyncClient(
                base_url=self._base, headers={"Authorization": f"Bearer {self._key}"}, timeout=self._to
            ) as c:
                r = await c.post("/chat/completions", json=payload)
                j = r.json()
                content = j["choices"][0]["message"].get("content", "")
                return CallResult(ok=r.is_success, status=r.status_code, data={"answer": content})
        except Exception as exc:  # noqa: BLE001
            return CallResult(ok=False, status=0, error=str(exc))

    async def health(self) -> CallResult:
        return CallResult(ok=bool(self._base), status=0, data={"agent": self._model})


class WebSocketConnector:
    """Connect to a websocket endpoint (streaming agents / services)."""

    def __init__(self, url: str, timeout: float = 30.0) -> None:
        self._url = url
        self._to = timeout

    async def send_recv(self, message: str) -> CallResult:
        try:
            import websockets  # type: ignore
        except Exception as exc:  # noqa: BLE001
            return CallResult(ok=False, status=0, error=f"websockets lib unavailable: {exc}")
        try:
            async with websockets.connect(self._url, open_timeout=self._to) as ws:  # type: ignore[attr-defined]
                await ws.send(message)
                reply = await asyncio.wait_for(ws.recv(), timeout=self._to)
                return CallResult(ok=True, status=200, data={"reply": reply})
        except Exception as exc:  # noqa: BLE001
            return CallResult(ok=False, status=0, error=str(exc))

    async def health(self) -> CallResult:
        return CallResult(ok=bool(self._url), status=0, data={"ws": self._url})


class MCPConnector:
    """Real Model Context Protocol (MCP) client.

    Connects to an MCP server through ANY supported transport and exposes the
    full MCP protocol (tools / prompts / resources / roots). Supported
    transports:

      - stdio       local subprocess server (command + args), spawned by MOON-AI
      - sse         Server-Sent Events HTTP endpoint
      - streamable  Streamable-HTTP endpoint (HTTP POST + SSE resumption)

    All transports are real outbound calls; nothing is mocked. Each transport
    and session stays open for the connector lifetime and is closed on failure
    or when the async context manager exits.

    Example (async):
        async with MCPConnector(record) as conn:
            tools = await conn.list_tools()
            r = await conn.call_tool("grep", {"pattern": "x"})
    """

    _SUPPORTED_TRANSPORTS = ("stdio", "sse", "streamable")

    def __init__(self, base_url: str | Any, timeout: float = 30.0) -> None:
        # Accept either a plain URL string (backward compat) or a
        # ConnectionRecord (full transport metadata).
        if hasattr(base_url, "kind") and hasattr(base_url, "transport"):
            self._record = base_url  # type: ignore[assignment]
            self._transport = str(self._record.transport or "").lower()
            self._url = str(self._record.url or "").rstrip("/")
            self._command = str(self._record.command or "")
            self._args = list(self._record.args or [])
            self._cwd = self._record.cwd
            self._env = self._record.env
        else:
            self._record = None  # type: ignore[assignment]
            self._url = str(base_url).rstrip("/")
            self._transport = "http"
            self._command = ""
            self._args = []
            self._cwd = None
            self._env = None
        self._to = timeout
        # Auto-infer transport when not explicitly set (backward compat).
        if self._transport == "http":
            if self._command:
                self._transport = "stdio"
            elif self._url or not self._url and not self._command:
                self._transport = "sse"
        self._session: Any = None
        self._stack: AsyncExitStack | None = None
        self._connect_lock = asyncio.Lock()

    # ------------------------------------------------------------------ impl
    async def connect(self) -> CallResult:
        """Open the underlying MCP transport. Real call, dispatches on transport."""
        async with self._connect_lock:
            transport = self._transport
            if transport not in self._SUPPORTED_TRANSPORTS:
                return CallResult(ok=False, status=0,
                                  error=f"unsupported MCP transport: {transport!r}")
            if self._session is not None:
                return CallResult(ok=True, status=200,
                                  data={"transport": transport, "mcp": "already connected"})
            if transport == "stdio" and not self._command:
                return CallResult(ok=False, status=0,
                                  error="MCP stdio transport requires an explicitly configured command")
            if transport != "stdio" and not self._url:
                return CallResult(ok=False, status=0,
                                  error=f"MCP {transport} transport requires a URL")

            stack = AsyncExitStack()
            try:
                if transport == "stdio":
                    from mcp.client.stdio import StdioServerParameters, stdio_client

                    server = StdioServerParameters(
                        command=self._command,
                        args=self._args,
                        env=self._env,
                        cwd=self._cwd,
                    )
                    read, write = await asyncio.wait_for(
                        stack.enter_async_context(stdio_client(server)),
                        timeout=self._to,
                    )
                elif transport == "sse":
                    from mcp.client.sse import sse_client

                    read, write = await asyncio.wait_for(
                        stack.enter_async_context(
                            sse_client(self._url, timeout=self._to, sse_read_timeout=self._to)
                        ),
                        timeout=self._to,
                    )
                else:
                    from importlib import import_module

                    streamable_module = import_module("mcp.client.streamable_http")
                    streamable_client = (
                        getattr(streamable_module, "streamable_http_client", None)
                        or getattr(streamable_module, "streamablehttp_client", None)
                    )
                    if streamable_client is None:
                        raise RuntimeError("installed MCP SDK has no streamable-HTTP client")
                    streams = await asyncio.wait_for(
                        stack.enter_async_context(streamable_client(self._url)),
                        timeout=self._to,
                    )
                    read, write = streams[0], streams[1]

                from mcp.client.session import ClientSession

                session = ClientSession(read, write)
                await asyncio.wait_for(stack.enter_async_context(session), timeout=self._to)
                initialized = await asyncio.wait_for(session.initialize(), timeout=self._to)
            except ModuleNotFoundError as exc:
                await stack.aclose()
                if exc.name == "mcp" or (exc.name and exc.name.startswith("mcp.")):
                    return CallResult(
                        ok=False, status=0,
                        error="MCP support is optional; install the project 'mcp' extra",
                    )
                return CallResult(ok=False, status=0,
                                  error=f"MCP {transport} connect failed ({type(exc).__name__})")
            except Exception as exc:  # noqa: BLE001
                try:
                    await stack.aclose()
                except Exception:
                    logger.debug("MCP transport cleanup failed", exc_info=True)
                reason = "configured command was not found" if isinstance(exc, FileNotFoundError) else type(exc).__name__
                return CallResult(
                    ok=False, status=0,
                    error=f"MCP {transport} connect failed ({reason})",
                )

            self._stack = stack
            self._session = session
            details = {"transport": transport, "mcp": "connected"}
            if hasattr(initialized, "protocolVersion"):
                details["protocol_version"] = initialized.protocolVersion
            return CallResult(ok=True, status=200, data=details)

    async def __aenter__(self) -> MCPConnector:
        result = await self.connect()
        if not result.ok:
            raise ConnectionError(result.error or "MCP connection failed")
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def close(self) -> None:
        stack, self._stack = self._stack, None
        self._session = None
        if stack is not None:
            try:
                await stack.aclose()
            except Exception:  # noqa: BLE001
                logger.exception("MCPConnector close failed")

    # ------------------------------------------------------------- protocol
    async def list_tools(self, cursor: str | None = None) -> CallResult:
        return await self._call("list_tools", *([cursor] if cursor is not None else []))

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> CallResult:
        return await self._call("call_tool", name, arguments or {})

    async def list_prompts(self, cursor: str | None = None) -> CallResult:
        return await self._call("list_prompts", *([cursor] if cursor is not None else []))

    async def get_prompt(self, name: str, arguments: dict[str, str] | None = None) -> CallResult:
        return await self._call("get_prompt", name, arguments or {})

    async def list_resources(self, cursor: str | None = None) -> CallResult:
        return await self._call("list_resources", *([cursor] if cursor is not None else []))

    async def read_resource(self, uri: str) -> CallResult:
        return await self._call("read_resource", uri)

    async def list_resource_templates(self, cursor: str | None = None) -> CallResult:
        return await self._call("list_resource_templates", *([cursor] if cursor is not None else []))

    async def list_roots(self) -> CallResult:
        return await self._call("list_roots")

    async def ping(self) -> CallResult:
        return await self._call("ping")

    # ----------------------------------------------------------------- low
    async def _call(self, method: str, *args, **kwargs) -> CallResult:
        allowed_methods = {
            "list_tools", "call_tool", "list_prompts", "get_prompt",
            "list_resources", "read_resource", "list_resource_templates",
            "list_roots", "ping",
        }
        if method not in allowed_methods:
            return CallResult(ok=False, status=0, error=f"unsupported MCP operation: {method}")
        if self._session is None:
            connected = await self.connect()
            if not connected.ok:
                return connected
        try:
            method_fn = getattr(self._session, method)
            result = await asyncio.wait_for(method_fn(*args, **kwargs), timeout=self._to)
            data = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
            return CallResult(ok=True, status=200, data=data)
        except asyncio.TimeoutError:
            await self.close()
            return CallResult(
                ok=False, status=0,
                error=f"MCP {method} timed out after {self._to:g}s; connection closed",
            )
        except Exception as exc:  # noqa: BLE001
            return CallResult(
                ok=False, status=0,
                error=f"MCP {method} failed ({type(exc).__name__})",
            )

    async def health(self) -> CallResult:
        """Initialize the configured endpoint to verify actual protocol reachability."""
        was_connected = self._session is not None
        result = await self.connect()
        if result.ok and not was_connected:
            await self.close()
        if result.ok:
            return CallResult(
                ok=True, status=200,
                data={"transport": self._transport, "mcp": "initialized"},
            )
        return result
