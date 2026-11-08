"""Browser automation tool (optional; requires playwright)."""

from __future__ import annotations

import asyncio
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
            addresses = [ipaddress.ip_address(record[4][0].split("%", 1)[0]) for record in records]
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
        "Open a public web URL and extract readable text. Unallowlisted or "
        "private destinations require operator approval or an explicit host allowlist "
        "(requires playwright). Model-supplied confirmation does not authorize egress."
    )

    def __init__(
        self,
        enabled: bool = False,
        permissions: ConnectorPermissionManager | None = None,
    ) -> None:
        self._enabled = enabled
        self._permissions = permissions or ConnectorPermissionManager()

    async def execute(self, url: str = "", **kwargs: Any) -> str:
        if not self._enabled:
            return "[browser disabled]"
        confirmed = kwargs.get("confirmed") is True
        allowed, reason = await _authorize_browser_url(
            url, self._permissions, confirmed=confirmed
        )
        if not allowed:
            return f"[browser] confirmation required or URL blocked: {reason}"
        browser = None
        result = ""
        cleanup_error = ""
        try:
            from playwright.async_api import async_playwright

            # Prevent GLib/GObject errors on Linux: force X11 backend instead of GTK.
            # Chromium's GTK integration emits "instance '0x... has no handler with id"
            # when launched on Linux without a compatible GTK stack; X11 avoids it.
            env = {
                "GDK_BACKEND": "x11",
                "GTK_BACKEND": "x11",
                "MOZ_ENABLE_WAYLAND": "0",
                "MOZ_WAYLAND": "0",
            }
            async with async_playwright() as p:
                browser = await p.chromium.launch(env=env)
                context = await browser.new_context(
                    service_workers="block",
                    java_script_enabled=False,
                )
                page = await context.new_page()

                async def guard_request(route, request) -> None:
                    request_allowed, _ = await _authorize_browser_url(
                        request.url, self._permissions, confirmed=confirmed
                    )
                    if request_allowed:
                        await route.continue_()
                    else:
                        await route.abort()

                await page.route("**/*", guard_request)
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                text = await page.locator("body").inner_text(timeout=5000)
                result = (text or "")[:2000]
        except Exception as exc:  # noqa: BLE001
            logger.warning("browser navigation failed: %s", exc)
            result = f"[browser error: {exc}]"
        finally:
            if browser is not None:
                try:
                    await browser.close()
                except Exception as exc:  # noqa: BLE001
                    logger.error("browser cleanup failed: %s", exc)
                    cleanup_error = str(exc)
        if cleanup_error:
            return f"[browser error: browser cleanup failed: {cleanup_error}]"
        return result
