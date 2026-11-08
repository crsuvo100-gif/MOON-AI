"""Connector permission manager -- least-privilege egress control.

Reuses the Capability system's PermissionManager policy tiers (SAFE /
CONFIRMATION / NEVER) and adds connector-specific scopes. Every outbound
connection is evaluated here before it is opened. Explicitly allowlisted hosts
are SAFE; everything else requires operator confirmation unless denied.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from app.capability.permission_manager import PermissionManager, PolicyLevel

# Network scopes used by the connector (added on top of the base manager).
NETWORK_SCOPES = (
    "network.egress",
    "network.service",
    "network.agent",
    "network.webhook",
)

def _allowed_set() -> set[str]:
    raw = os.environ.get("ALLOWED_EGRESS_HOSTS", "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


@dataclass
class EgressDecision:
    allowed: bool
    tier: PolicyLevel
    reason: str


class ConnectorPermissionManager(PermissionManager):
    """Permission checks for outbound connections, layered on PermissionManager."""

    def egress_decision(self, host: str, scope: str = "network.egress") -> EgressDecision:
        """Decide if a connection to `host` under `scope` may proceed.

        - ALLOWED_EGRESS_HOSTS -> SAFE.
        - secrets.read scope -> NEVER (operator must supply at runtime, never auto).
        - everything else, including loopback and private addresses, requires
          explicit confirmation unless globally denied.
        """
        if scope == "secrets.read":
            return EgressDecision(False, PolicyLevel.NEVER, "credential reads require explicit operator supply")
        h = (host or "").lower()
        if h in _allowed_set():
            return EgressDecision(True, PolicyLevel.SAFE, f"host '{h}' is allowlisted")
        return EgressDecision(
            False, PolicyLevel.CONFIRMATION,
            f"outbound connection to '{h}' needs operator confirmation (not allowlisted)",
        )

    def may_auto(self, scope: str, host: str = "") -> bool:
        """True only when this connection may proceed WITHOUT operator confirmation."""
        if scope in ("secrets.read",):
            return False
        d = self.egress_decision(host, scope)
        return d.allowed and d.tier == PolicyLevel.SAFE
