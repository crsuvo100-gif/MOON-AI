"""Browser automation tool (optional; requires playwright)."""

from __future__ import annotations

import logging
from typing import Any

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


class BrowserTool(BaseTool):
    name = "browser"
    description = "Open a URL and extract readable text (requires playwright)."

    def __init__(self, enabled: bool = False) -> None:
        self._enabled = enabled

    async def execute(self, url: str = "", **kwargs: Any) -> str:
        if not self._enabled:
            return "[browser disabled]"
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
                page = await browser.new_page()
                await page.goto(url or "about:blank")
                text = await page.inner_text("body")
                await browser.close()
                return (text or "")[:2000]
        except Exception as exc:  # noqa: BLE001
            return f"[browser error: {exc}]"
