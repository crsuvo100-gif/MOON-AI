"""Capability registry for the Cybersecurity Laboratory.

Built-in capabilities are the honest, immediately runnable foundation:
read-only local analysis, a deterministic teaching echo, a secrets-redaction
launcher, a policy demonstration capability, a strictly loopback-only passive
network probe, and a tier-3 default-block demonstration capability.

Nothing here does anything destructive or exfiltrative. Every capability is a
MOON-operated, auditable capability with a declared risk tier and scope.
"""
from __future__ import annotations

import logging
from pathlib import Path

from app.laboratory.lifecycle import LifecycleStore
from app.laboratory.model import Capability, RiskTier
from app.laboratory import get_laboratory

logger = logging.getLogger(__name__)


def _default_capabilities() -> list[Capability]:
    """Return the bundled lab capability catalog (no side effects)."""
    return [
        Capability(
            name="local_data_inventory",
            category="local-analysis",
            title="MOON data inventory",
            description=(
                "Read-only summary of MOON's own runtime directories "
                "(data/, logs/, capabilities/, laboratory/): file counts, total "
                "bytes and top-level layout. Never reads secrets and never "
                "modifies anything."
            ),
            tier=RiskTier.READ_ONLY,
            required_scope=("workspace.read",),
            parameters={"paths": ["data", "logs", "capabilities", "app/logs"]},
            adapter="local_inventory",
            status="available",
            health="healthy",
            source="bundled",
            notes="Read-only local introspection. Safe to run by default.",
        ),
        Capability(
            name="local_env_probe",
            category="local-analysis",
            title="Local configuration/env envelope probe",
            description=(
                "Read-only inspection of the paths and config keys MOON is "
                "configured to use (model_base_url, memory backend, terminal "
                "host/port, laboratory root). Prints key names and shapes, "
                "masks any value that looks like a secret."
            ),
            tier=RiskTier.LOW_RISK,
            required_scope=("workspace.read", "config.read"),
            parameters={},
            adapter="local_env_probe",
            status="available",
            health="healthy",
            source="bundled",
            notes="Reveals shape only. Sensitive values are redacted.",
        ),
        Capability(
            name="test_echo",
            category="testing",
            title="Deterministic harmless echo",
            description=(
                "A small, fully validated, always-succeeding capability used to "
                "prove the laboratory execution path end-to-end. Returns the "
                "requested message with a timestamp and requires no external "
                "dependency."
            ),
            tier=RiskTier.READ_ONLY,
            required_scope=("test.echo",),
            parameters={"message": "hello from laboratory"},
            adapter="echo",
            status="available",
            health="healthy",
            source="bundled",
            notes="The canonical approved test capability for MOON runtime tests.",
        ),
        Capability(
            name="redaction_test",
            category="testing",
            title="Secrets-redaction coverage test",
            description=(
                "Verifies that sensitive-looking values in task/parameter text "
                "are replaced before the laboratory persists or logs them. "
                "Returns the redacted form of its input."
            ),
            tier=RiskTier.READ_ONLY,
            required_scope=("test.redact",),
            parameters={"text": "api_key=sk-or-xxx token=supersekret"},
            adapter="redact",
            status="available",
            health="healthy",
            source="bundled",
            notes="Proof of the redaction layer; output always sanitized.",
        ),
        Capability(
            name="loopback_tcp_probe",
            category="network",
            title="Strictly loopback TCP probe",
            description=(
                "Passive readiness check that only touches localhost "
                "(127.0.0.1 / ::1). It never sends packets to third-party "
                "hosts and never exfiltrates data. Requires an explicit "
                "approval record tied to this capability."
            ),
            tier=RiskTier.CONTROLLED_TEST,
            required_scope=("network.loopback",),
            parameters={"host": "127.0.0.1", "port": 8777, "count": 3},
            adapter="loopback_probe",
            status="available",
            health="unknown",
            source="bundled",
            notes="Policy-gated. Ask MOON to approve before use.",
        ),
        Capability(
            name="policy_echo",
            category="policy-demo",
            title="High-impact policy demonstration",
            description=(
                "Deliberately blocked unless a matching approval record exists. "
                "Used to demonstrate that MOON honors least privilege and that "
                "a request without approval is denied."
            ),
            tier=RiskTier.HIGH_IMPACT,
            required_scope=("admin.exempt",),
            parameters={"message": "do not run without approval"},
            adapter="policy_echo",
            status="available",
            health="unknown",
            source="bundled",
            notes="BLOCK unless approvaled; never run by default.",
        ),
    ]


class LaboratoryRegistry:
    """In-memory catalog of the laboratory capabilities, backed by policy."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._caps: dict[str, Capability] = {}
        for rec in _default_capabilities():
            self._caps[rec.name] = rec
        self._lifecycle = LifecycleStore(self.root / "capabilities")
        for name in self._caps:
            self._lifecycle.transition(name, "ENABLED", {"source": "bundled"})

    # -- lookup -------------------------------------------------------- #
    def get(self, name: str) -> Capability | None:
        return self._caps.get(name.lower())

    def all(self) -> list[Capability]:
        return list(self._caps.values())

    def by_tier(self, tier: int) -> list[Capability]:
        return [c for c in self._caps.values() if int(c.tier) == tier]

    def health(self, name: str) -> str:
        c = self.get(name)
        return c.health if c else "unknown"

    def status(self, name: str) -> str:
        c = self.get(name)
        return c.status if c else "unknown"

    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {"available": 0, "disabled": 0, "blocked": 0}
        for c in self._caps.values():
            counts[c.status] = counts.get(c.status, 0) + 1
        return counts

    def to_list(self) -> list[dict]:
        return [c.to_dict() for c in self._caps.values()]
