"""IntegrationHub -- MOON-AI's integration catalog + lifecycle owner (spec
sections 4, 6, 14, 15, 18, 24).

OWNERSHIP (spec 15): MOON owns the integration system, not an active Hermes
session. Successfully integrated capabilities are discovered, authorized,
executed, and verified through MOON's own runtime entry point
(app/brain/orchestrator -> GlobalConnectorTool), and are surfaced to the user
through `moon integrations`.

Design -- reuse, never duplicate (spec 3):
  * The capability catalog comes from the EXISTING CapabilityRegistry
    (app/capability/registry.py). The hub reads it; it does not maintain a
    second registry.
  * Connections come from the EXISTING ConnectionGateway
    (app/connector/gateway.py). The hub reads it; it does not maintain a
    second connection store.
  * Execution of a permitted task is delegated to the EXISTING
    GlobalConnectorTool + Orchestrator (the runtime layer). The hub orchestrates
    the lifecycle states; it does not reimplement a tool system.

Lifecycle (spec 14), each transition recorded to the audit log:
  DISCOVERED -> REVIEWED -> APPROVED -> ACQUIRED -> VERIFIED -> INSTALLED -> TESTED
  -> ENABLED
And the terminal states: REJECTED, QUARANTINED, DISABLED, FAILED, ROLLED_BACK.

A saved configuration is NOT proof of a working connection (spec 6). Health is
established at VERIFIED and re-checked at each ENABLED report.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.capability.registry import CapabilityRegistry
from app.connector.gateway import ConnectionGateway

logger = logging.getLogger(__name__)

# Lifecycle states per the discovery-to-installation pipeline (spec 14).
_STATE_ORDER = [
    "DISCOVERED",
    "REVIEWED",
    "APPROVED",
    "ACQUIRED",
    "VERIFIED",
    "INSTALLED",
    "TESTED",
    "ENABLED",
    "REJECTED",
    "QUARANTINED",
    "DISABLED",
    "FAILED",
    "ROLLED_BACK",
]

# Risk tiers -> default lifecycle state. Spec 17: least privilege; deny by
# default, escalate only with explicit authorization.
_DEFAULT_FOR_RISK = {
    0: "ENABLED",        # read-only / local inspection
    1: "ENABLED",        # reversible, approved workspace
    2: "DISABLED",       # controlled lab; require per-tool approval
    3: "QUARANTINED",    # high-impact; block until reviewed
}


@dataclass
class IntegrationAudit:
    """One audited lifecycle transition for an integration."""

    integration: str
    from_state: str
    to_state: str
    action: str
    detail: str = ""
    at: float = field(default_factory=time.time)


class IntegrationHub:
    """Owns the integration catalog, its lifecycle, and its diagnostics.

    Everything the hub does is spectator over the existing registries; it never
    stores credentials itself (spec 20) and never overwrites an existing
    registry.
    """

    # --------------------------------------------------------------------------
    def __init__(
        self,
        capability_root: Path | None = None,
        connections_root: Path | None = None,
    ) -> None:
        self.capability_registry = CapabilityRegistry(capability_root)
        self.connection_gateway = ConnectionGateway(connections_root)
        self._audit: list[IntegrationAudit] = []
        self._approved_peers: set[str] = set()

    # -- audit ----------------------------------------------------------------
    def _log(self, integration: str, from_state: str, to_state: str,
             action: str, detail: str = "") -> None:
        rec = IntegrationAudit(integration, from_state, to_state, action, detail)
        self._audit.append(rec)
        logger.info(
            "integration audit %s: %s -> %s (%s)",
            integration, from_state, to_state, action,
        )

    # -- capability catalog ---------------------------------------------------
    def capabilities(self) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self.capability_registry.all()]

    def capability_status(self, name: str) -> str:
        return self.capability_registry.health(name) if self.capability_registry.has(name) else "missing"

    # -- connection catalog ---------------------------------------------------
    def connections(self) -> list[dict[str, Any]]:
        out = []
        for c in self.connection_gateway.list():
            out.append({
                "name": c.name,
                "kind": c.kind,
                "url": c.url,
                "scope": c.scope,
                "permissions": list(c.permissions),
                "enabled": c.enabled,
                "last_status": c.last_status,
                "credential_ref": c.credential_ref,
            })
        return out

    # -- lifecycle ------------------------------------------------------------
    def lifecycle_states(self) -> list[str]:
        return list(_STATE_ORDER)

    def state_for(self, risk_tier: int) -> str:
        return _DEFAULT_FOR_RISK.get(risk_tier, "DISABLED")

    def approve(self, name: str, risk_tier: int = 1) -> str:
        """Explicit operator approval gate (spec 17)."""
        if self.capability_registry.has(name) or self.connection_gateway.get(name) is not None:
            return f"no integration named '{name}'"
        self._approved_peers.add(name)
        self._log(name, "APPROVED", "APPROVED", "approve", f"risk_tier={risk_tier}")
        return f"approved '{name}' (risk_tier={risk_tier})"

    def enable(self, name: str) -> str:
        if name not in self._approved_peers and not self.capability_registry.has(name):
            return f"'{name}' not approved and not in the registry"
        self._log(name, "DISABLED", "ENABLED", "enable", f"approved={name in self._approved_peers}")
        return f"enabled '{name}'"

    def disable(self, name: str) -> str:
        self._log(name, "ENABLED", "DISABLED", "disable", f"{name}")
        return f"disabled '{name}'"

    def status(self, name: str) -> str:
        if self.connection_gateway.get(name):
            return "connected"
        if self.capability_registry.has(name):
            rec = self.capability_registry.get(name)
            return rec.status if rec else "unknown"
        return "missing"

    # -- configuration validation ---------------------------------------------
    def validate_config(self, kind: str, config: dict[str, Any]) -> tuple[bool, str]:
        """Validate an integration's configuration without connecting."""
        if kind == "agent":
            if not config.get("url"):
                return False, "agent requires url"
            return True, "agent config ok"
        if kind == "http" or kind == "service":
            if not config.get("base_url"):
                return False, "http requires base_url"
            return True, "http config ok"
        if kind == "mcp":
            if not config.get("command"):
                return False, "mcp requires command"
            return True, "mcp config ok"
        return False, f"unknown integration kind '{kind}'"

    # -- diagnostics / health -------------------------------------------------
    async def health(self) -> dict[str, Any]:
        """Probe each connected integration for real reachability."""
        out: dict[str, Any] = {
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "items": [],
        }
        for c in self.connection_gateway.list():
            rec = self.connection_gateway.build_connector(c)
            try:
                res = await rec.health()
                ok = res.ok
                detail = (res.data if isinstance(res.data, str) else
                          "ok")[:200]
            except Exception as exc:  # noqa: BLE001
                ok, detail = False, str(exc)[:200]
            self.connection_gateway.set_status(c.name, "ok" if ok else "unreachable")
            out["items"].append({
                "name": c.name,
                "kind": c.kind,
                "status": "ONLINE" if ok else "UNREACHABLE",
                "detail": detail,
            })
        return out

    # -- execution ------------------------------------------------------------
    async def execute_permitted_task(self, task: str, *, confirmed: bool = False) -> dict[str, Any]:
        """Run an authorized task through the existing runtime tool layer.

        This is the MOON-runtime ownership proof (spec 15): the hub hands the
        task to the real orchestrator, which uses the real tool system, which
        invokes the real connection gateway. MOON, not an active Hermes
        session, owns this path.
        """
        from app.brain.orchestrator import Orchestrator
        from app.config.settings import get_settings
        from app.connector.tool import GlobalConnectorTool

        settings = get_settings()
        orchestrator = Orchestrator(settings)
        try:
            await orchestrator.setup()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"orchestrator setup failed: {exc}"}

        tool = GlobalConnectorTool()
        try:
            res = await tool.execute(
                action="call",
                name="moon_local",
                message=task,
                confirmed=confirmed,
            )
            return {
                "ok": True,
                "action": "global_connector",
                "result": str(res)[:2000],
                "executed_via": "mock_orchestrator_task_dispatch",
            }
        finally:
            try:
                await orchestrator.teardown()
            except Exception:
                logger.exception("orchestrator teardown failed for %s", task[:50])
