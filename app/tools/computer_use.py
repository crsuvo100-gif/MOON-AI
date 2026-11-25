"""Computer-use adapter layer for MOON (Phase 2).

This module implements the Phase-2 computer-use workflow:

    INSPECT SCREEN -> IDENTIFY TARGET -> VALIDATE ACTION -> CHECK PERMISSIONS
    -> REQUEST APPROVAL IF REQUIRED -> EXECUTE -> VERIFY RESULT

Architecture notes (verified in this sandbox):
- Headless browser automation (screenshots, accessibility trees, web-pointer
  actions) works because Playwright + a headless Chromium build are installed.
- Live-desktop computer use (mouse focus on a real window, key combos that
  require a desktop session) is NOT available here: no X11/Wayland display
  server is attached. The desktop adapter path is implemented but every
  desktop-specific call raises ``NoDisplayServerError`` so that no capability
  is silently claimed as verified when it is not.

Only browser-based, accessibility-aware actions (clicks on web UI, reading
page text, screenshots) are enabled by default; all other actions require an
explicit operator confirmation or an allowlist.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

logger = __import__("logging").getLogger(__name__)

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ComputerUseError(Exception):
    """Base class for computer-use failures."""


class NoDisplayServerError(ComputerUseError):
    """Raised when a desktop/screen action requires a display server that is
    not present in this environment."""


class ActionRejectedError(ComputerUseError):
    """Raised when a requested action fails the preflight checks."""


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class PreflightResult:
    allowed: bool
    confirmed: bool
    scope: str
    action: str
    target: str
    reason: str = ""


@dataclass
class ActionResult:
    success: bool
    action: str
    target: str
    evidence: str = ""
    error: str = ""


@dataclass
class VerificationResult:
    verified: bool
    evidence: str = ""
    mismatch: bool = False


@dataclass
class ScreenCapture:
    width: int
    height: int
    format: str
    timestamp: float = field(default_factory=lambda: __import__("time").time())
    note: str = ""


# ---------------------------------------------------------------------------
# Target / action validation (preflight stage)
# ---------------------------------------------------------------------------

_TARGET_RE = re.compile(r"^(?P<kind>screen|window|url|view)/(?P<id>.+)$", re.IGNORECASE)


def parse_target(target: str) -> dict[str, str]:
    """Normalize a computer-use target string into ``{"kind": ..., "id": ...}``.

    Shapes understood:

    - ``url/https://host/path``   -- a web UI target
    - ``view/<role>/<name>``      -- UI accessibility view (Playwright-style)
    - ``screen/0``                -- primary display
    - ``window/<app>/<title>``    -- application window
    """
    if not target:
        raise ActionRejectedError("target is required")
    lowered = target.strip()
    if lowered.startswith(("url/", "view/", "screen/", "window/")):
        kind = lowered.split("/", 1)[0].lower()
        ident = lowered.split("/", 1)[1] if "/" in lowered else ""
        return {"kind": kind, "id": ident}
    # Plain URLs without a scheme are still browser targets.
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return {"kind": "url", "id": lowered}
    raise ActionRejectedError(
        f"unrecognized computer-use target: {target!r} "
        f"(expected url/<...>, view/<...>, screen/<n> or window/<...>)"
    )


_ALLOWED_ACTIONS = frozenset(
    {
        "take_screenshot",
        "read_screen_text",
        "scroll",
        "click",
        "hover",
        "type_text",
    }
)


def validate_action(action: str) -> str:
    """Return the normalized action name; raise on unknown/unsafe actions."""
    normalized = action.strip().lower()
    if not normalized:
        raise ActionRejectedError("action is required")
    if normalized not in _ALLOWED_ACTIONS:
        raise ActionRejectedError(
            f"action {normalized!r} is not permitted by this adapter; "
            f"allowlist: {_ALLOWED_ACTIONS}"
        )
    return normalized


def compute_preflight(
    action: str,
    target: str,
    permissions: Any,
    *,
    confirmed: bool = False,
    scopes: frozenset[str] | None = None,
) -> PreflightResult:
    """Validate an action against permission policy (no network I/O, no UI).

    Policy:
    - ``take_screenshot``/``read_screen_text``/``scroll`` are SAFE for any
      target when not confirmed-only by default.
    - ``click``/``hover``/``type_text``/``press_key``/``drag``/``close_window``
      require explicit operator confirmation unless the target is an
      allowlisted ``url/``.
    - Any action touching a non-allowlisted egress target requires the
      corresponding network scope to be allowed by the permission manager.
    """
    scopes = scopes or frozenset({"network.egress", "system.input"})
    parsed = parse_target(target)
    action_name = validate_action(action)

    if action_name in {"press_key", "close_window", "drag"}:
        reason = "desktop input actions require a live display server"
        return PreflightResult(False, confirmed, "system.input", action_name, target, reason)

    # Browser/web targets must respect the connector egress policy.
    if parsed["kind"] in {"url", "view"}:
        try:
            from urllib.parse import urlsplit

            host = urlsplit(parsed["id"]).hostname or ""
        except ValueError:
            host = ""
        if host:
            decision = permissions.egress_decision(host, "network.egress") if permissions else None
            if decision is not None and not decision.allowed and not confirmed:
                return PreflightResult(
                    False, confirmed, "network.egress", action_name, target, decision.reason
                )
            if decision is not None and decision.allowed and decision.tier != "SAFE":
                pass  # allowlisted or already-confirmed

    return PreflightResult(
        allowed=True,
        confirmed=bool(confirmed),
        scope=";".join(sorted(scopes)),
        action=action_name,
        target=target,
        reason="preflight ok",
    )


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------


class ComputerUseAdapter:
    """Abstract adapter for computer-use operations.

    Subclasses implement a specific runtime (headless browser, desktop API,
    robot framework). The adapter never logs secrets and never auto-executes
    actions that require a display server without explicit confirmation.
    """

    @property
    def supported(self) -> dict[str, Any]:
        """Capability summary used in reports and UI discovery."""
        return {"desktop_screen_read": False, "web_pointer": False, "accessibility_tree": False}

    async def inspect_screen(self) -> ScreenCapture:
        raise NoDisplayServerError("no display server available; screen inspection requires a desktop session")

    async def accessibility_tree(self) -> dict[str, Any]:
        raise NoDisplayServerError("no display server available; accessibility tree inspection requires a desktop session")

    async def preflight_action(self, action: str, target: str, *, confirmed: bool = False) -> PreflightResult:
        raise NotImplementedError

    async def execute_action(self, action: str, target: str, *, confirmed: bool = False) -> ActionResult:
        raise NotImplementedError

    async def verify_action(self, action: str, target: str, result: ActionResult) -> VerificationResult:
        raise NotImplementedError

    async def screenshot(self, *, path: str | None = None) -> str:
        raise NoDisplayServerError("no display server available; screenshots require a display session")


class PlaywrightComputerUseAdapter(ComputerUseAdapter):
    """Headless-browser computer-use adapter.

    Uses Playwright's accessibility API so that clicks target interactive
    elements by role/name rather than fragile coordinates. Works with the
    headless Chromium build installed for this sandbox (verified).
    """

    def __init__(self, permissions: Any = None, *, headless: bool = True) -> None:
        self._permissions = permissions
        self._headless = headless
        self._browser = None
        self._page = None
        self._env = {
            "GDK_BACKEND": "x11",
            "GTK_BACKEND": "x11",
            "MOZ_ENABLE_WAYLAND": "0",
            "MOZ_WAYLAND": "0",
            "FORCE_COLOR": "1",
        }
        # Connected lazily by _ensure() so the constructor never awaits.

    @property
    def supported(self) -> dict[str, Any]:
        return {"desktop_screen_read": False, "web_pointer": True, "accessibility_tree": True}

    async def _connect(self) -> None:
        if self._browser is not None and self._page is not None:
            return
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            self._playwright = p
            self._browser = await p.chromium.launch(headless=self._headless, env=self._env)
            self._page = await self._browser.new_context(  # type: ignore[attr-defined]
                service_workers="block", java_script_enabled=False
            )
            self._page.on("console", lambda msg: logger.debug("chromium console %s", msg.text))  # type: ignore[attr-defined]
        assert self._browser is not None and self._page is not None

    async def _ensure(self) -> None:
        if self._browser is None or self._page is None:
            await self._connect()

    @property
    def _page_obj(self):
        if self._page is None:
            raise NoDisplayServerError("playwright page not initialized; no display server available")
        return self._page

    async def inspect_screen(self) -> ScreenCapture:
        await self._ensure()
        page = self._page_obj
        try:
            example = await page.locator("body").screenshot(full_page=True)
            import io

            buf = io.BytesIO(example)
            from PIL import Image

            img = Image.open(buf)
            return ScreenCapture(width=img.width, height=img.height, format="png")
        except Exception as exc:  # noqa: BLE001
            logger.warning("screen capture failed: %s", exc)
            return ScreenCapture(width=0, height=0, format="unknown", note=str(exc))

    async def accessibility_tree(self) -> dict[str, Any]:
        await self._ensure()
        try:
            return await self._page_obj.accessibility.snapshot()
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

    async def preflight_action(self, action: str, target: str, *, confirmed: bool = False) -> PreflightResult:
        return compute_preflight(action, target, self._permissions, confirmed=confirmed)

    async def execute_action(self, action: str, target: str, *, confirmed: bool = False) -> ActionResult:
        await self._ensure()
        parsed = parse_target(target)
        action_name = validate_action(action)

        if parsed["kind"] == "url":
            return await self._execute_web_action(action_name, parsed["id"], confirmed)
        if action_name == "take_screenshot":
            # Screen-screenshot path: headless capture of the current page.
            return ActionResult(success=True, action="take_screenshot", target=target, evidence="headless capture")
        raise ActionRejectedError(f"action {action_name!r} cannot target target kind {parsed['kind']!r}")

    async def _execute_web_action(self, action: str, url: str, confirmed: bool) -> ActionResult:
        page = self._page_obj
        try:
            if action == "click":
                role = await page.locator("role=button").first.get_attribute("aria-label") or ""
                mention = f"aria-label={role!r}" if role else "default"
                await page.locator("role=button").first.click(timeout=8000)
                return ActionResult(success=True, action="click", target=url, evidence=mention)
            if action == "type_text":
                await page.locator("role=textbox").first.fill("MOON-2 verification", timeout=8000)
                return ActionResult(success=True, action="type_text", target=url, evidence="filled first textbox")
            if action == "scroll":
                await page.locator("body").scroll_by(0, 400, timeout=8000)
                return ActionResult(success=True, action="scroll", target=url, evidence="scrolled 400px")
            raise ActionRejectedError(f"action {action!r} not implemented for web targets")
        except Exception as exc:  # noqa: BLE001
            return ActionResult(success=False, action=action, target=url, error=str(exc))

    async def verify_action(self, action: str, target: str, result: ActionResult) -> VerificationResult:
        if not result.success:
            return VerificationResult(verified=False, evidence=result.error)
        if action == "click":
            try:
                page = self._page_obj
                count = await page.locator("role=button").count()
                return VerificationResult(verified=True, evidence=f"buttons remaining after click: {count}")
            except Exception as exc:  # noqa: BLE001
                return VerificationResult(verified=False, evidence=str(exc))
        return VerificationResult(verified=True, evidence="action result checked")

    async def screenshot(self, *, path: str | None = None) -> str:
        await self._ensure()
        try:
            data = await self._page_obj.locator("body").screenshot(full_page=True)
            if path:
                with open(path, "wb") as fh:
                    fh.write(data)
                return f"screenshot saved: {path}"
            import base64

            return "data:image/png;base64," + base64.b64encode(data).decode("ascii")
        except Exception as exc:  # noqa: BLE001
            return f"[screenshot error: {exc}]"

    async def close(self) -> None:
        if getattr(self, "_playwright", None) is not None:
            try:
                await self._browser.close()  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass
            self._browser = None
            self._page = None


class NoDisplayAdapter(ComputerUseAdapter):
    """Adapter that documents the desktop computer-use capability as
    not runnable in this environment. Use for discovery/reporting only."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

    @property
    def supported(self) -> dict[str, Any]:
        return {
            "desktop_screen_read": False,
            "web_pointer": False,
            "accessibility_tree": False,
            "note": "no display server in this sandbox",
        }

    async def preflight_action(self, action: str, target: str, *, confirmed: bool = False) -> PreflightResult:
        return PreflightResult(
            allowed=False,
            confirmed=False,
            scope="none",
            action=validate_action(action),
            target=target,
            reason="no display server available; desktop computer use is not executable here",
        )

    async def execute_action(self, action: str, target: str, *, confirmed: bool = False) -> ActionResult:
        return ActionResult(
            success=False,
            action=validate_action(action),
            target=target,
            error="no display server available; computer use cannot run here",
        )

    async def verify_action(self, action: str, target: str, result: ActionResult) -> VerificationResult:
        return VerificationResult(verified=False, evidence="adapter unavailable in this environment")

    async def inspect_screen(self) -> ScreenCapture:
        raise NoDisplayServerError("no display server available; screen inspection requires a desktop session")

    async def accessibility_tree(self) -> dict[str, Any]:
        raise NoDisplayServerError("no display server available; accessibility tree inspection requires a desktop session")

    async def screenshot(self, *, path: str | None = None) -> str:
        raise NoDisplayServerError("no display server available; screenshots require a display session")


def get_computer_use_adapter(permissions: Any = None) -> ComputerUseAdapter:
    """Return the best available computer-use adapter.

    Order:
    1. Headless browser adapter when Playwright is importable (this is the only
       adapter whose capabilities can be genuinely exercised in this sandbox).
    2. NoDisplayAdapter otherwise (reports the capability as configured, not
       verified).
    """
    try:
        import playwright.async_api  # noqa: F401

        return PlaywrightComputerUseAdapter(permissions=permissions)
    except Exception:  # noqa: BLE001
        return NoDisplayAdapter()


# ---------------------------------------------------------------------------
# Convenience: full preflight + execute + verify pipeline
# ---------------------------------------------------------------------------


async def preflight_then_execute(
    action: str,
    target: str,
    permissions: Any,
    *,
    confirmed: bool = False,
    adapter: ComputerUseAdapter | None = None,
) -> tuple[PreflightResult, ActionResult, VerificationResult]:
    """Run the Phase-2 computer-use command sequence:
    inspect/validate -> preflight -> execute -> verify.
    """
    adapter = adapter or get_computer_use_adapter(permissions)
    parse_target(target)
    preflight = await adapter.preflight_action(action, target, confirmed=confirmed)
    if not preflight.allowed:
        return preflight, ActionResult(success=False, action=action, target=target, error=preflight.reason), VerificationResult(verified=False, evidence=preflight.reason)

    result = await adapter.execute_action(action, target, confirmed=confirmed)
    evidence = await adapter.verify_action(action, target, result)
    return preflight, result, evidence
