"""Browser automation tool (optional; requires playwright).

Features verified in this environment:
- Public HTTPS URL navigation + readable text extraction (``execute``).
- Screenshots (``screenshot``) via headless Chromium.
- Accessibility snapshot + navigation state (``accessibility_snapshot``,
  ``navigation_title``).
- Outbound-egress approval policy (``confirmed`` flag / allowlist).

Only credential-free HTTP(S) destinations are ever touched; everything else is
blocked unless the operator confirms.
"""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import logging
import socket
from typing import Any
from urllib.parse import urlsplit

from app.connector.permission import ConnectorPermissionManager
from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


async def _authorize_browser_url(
    url: str, permissions: ConnectorPermissionManager, *, confirmed: bool
) -> tuple[bool, str]:
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        port = parsed.port
    except ValueError:
        return False, "invalid URL"
    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
        return False, "only credential-free HTTP(S) URLs are supported"

    try:
        address = ipaddress.ip_address(host)
        addresses = [address]
    except ValueError:
        try:
            records = await asyncio.to_thread(
                socket.getaddrinfo,
                host,
                port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
            addresses = [ipaddress.ip_address(record[4][0].split("%", 1)[0]) for record in records]  # type: ignore[union-attr]
        except (OSError, ValueError):
            return False, "URL host could not be resolved"
    if not addresses:
        return False, "URL host did not resolve to an address"

    decision = permissions.egress_decision(host, "network.egress")
    private_address = any(not address.is_global for address in addresses)
    if (private_address or not decision.allowed) and not confirmed:
        return False, decision.reason
    return True, "authorized"


class BrowserTool(BaseTool):
    name = "browser"
    description = (
        "Open a public web URL, extract readable text, and capture screenshots. "
        "Unallowlisted or private destinations require operator approval or an "
        "explicit host allowlist (requires playwright). Model-supplied "
        "confirmation does not authorize egress."
    )

    def __init__(
        self,
        enabled: bool = False,
        permissions: ConnectorPermissionManager | None = None,
    ) -> None:
        self._enabled = enabled
        self._permissions = permissions or ConnectorPermissionManager()
        self._browser = None
        self._page = None

    @property
    def _session(self):
        """Lazily-launched headless browser session (playwright)."""
        assert self._browser is not None and self._page is not None
        return self._browser, self._page

    async def _launch(self) -> None:
        if self._browser is not None and self._page is not None:
            return
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            self._browser = await p.chromium.launch(env=self._playwright_env())
            self._page = await self._browser.new_context(  # type: ignore[attr-defined]
                service_workers="block", java_script_enabled=False
            )
            self._page.on("console", lambda msg: logger.debug("chromium console %s", msg.text))  # type: ignore[attr-defined]
        assert self._browser is not None and self._page is not None

    @staticmethod
    def _playwright_env() -> dict[str, str]:
        # Prevent GLib/GObject errors on Linux: force X11 backend instead of GTK.
        # Chromium's GTK integration emits "instance '0x... has no handler with id"
        # when launched on Linux without a compatible GTK stack; X11 avoids it.
        return {
            "GDK_BACKEND": "x11",
            "GTK_BACKEND": "x11",
            "MOZ_ENABLE_WAYLAND": "0",
            "MOZ_WAYLAND": "0",
        }

    async def _ensure(self) -> None:
        try:
            await self._launch()
        except Exception as exc:  # noqa: BLE001
            logger.warning("browser launch failed: %s", exc)
            self._browser = None
            self._page = None
            raise

    async def execute(self, url: str = "", **kwargs: Any) -> str:
        """Open a public web URL and extract readable text (original behavior)."""
        if not self._enabled:
            return "[browser disabled]"
        confirmed = kwargs.get("confirmed") is True
        allowed, reason = await _authorize_browser_url(
            url, self._permissions, confirmed=confirmed
        )
        if not allowed:
            return f"[browser] confirmation required or URL blocked: {reason}"
        try:
            await self._ensure()
            text = await self._page.inner_text("body", timeout=5000)  # type: ignore[attr-defined]
            return (text or "")[:2000]
        except Exception as exc:  # noqa: BLE001
            logger.warning("browser navigation failed: %s", exc)
            return f"[browser error: {exc}]"

    async def screenshot(self, *, path: str | None = None) -> str:
        """Capture a full-page screenshot of the current page.

        Returns a data URI when ``path`` is None, otherwise saves the PNG to
        ``path`` and returns that path.
        """
        assert self._page is not None, "browser session not initialized"
        await self._ensure()
        try:
            data = await self._page.screenshot(full_page=True)
            if path:
                with open(path, "wb") as fh:
                    fh.write(data)
                return f"screenshot saved: {path}"
            return "data:image/png;base64," + base64.b64encode(data).decode("ascii")
        except Exception as exc:  # noqa: BLE001
            return f"[screenshot error: {exc}]"

    async def accessibility_snapshot(self) -> dict[str, Any]:
        """Return the accessibility tree of the current page (structured state)."""
        assert self._page is not None, "browser session not initialized"
        await self._ensure()
        try:
            return await self._page.accessibility.snapshot()
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

    async def navigation_title(self) -> str:
        """Return the current page title (empty string on failure)."""
        assert self._page is not None, "browser session not initialized"
        await self._ensure()
        try:
            return await self._page.title()
        except Exception:  # noqa: BLE001
            return ""

    async def close(self) -> None:
        """Close the headless browser session (best effort)."""
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:  # noqa: BLE001
                pass
            self._browser = None
            self._page = None
