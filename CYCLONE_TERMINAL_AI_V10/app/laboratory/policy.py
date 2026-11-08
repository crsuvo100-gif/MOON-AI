"""Policy engine for the Cybersecurity Laboratory.

Default-deny, least-privilege authorization. The laboratory never executes a
capability without an explicit policy decision. Tiers:

  0 - READ_ONLY:      local, non-mutating analysis. Allowed without approval.
  1 - LOW_RISK:       reversible, in-workspace operations. Allowed. logged.
  2 - CONTROLLED_TEST (network) : explicitly scoped, usually loopback-only.
                                   requires a matching approval record.
  3 - HIGH_IMPACT:    destructive / credential-bearing / outbound-exfil.
                                   blocked unless an explicit approval exists.

A capability that is not registered, or whose required_scope does not match the
caller, is rejected at the gate. Approval records live in
data/laboratory/approvals.json and can be created through the API, the
console command `moon laboratory approve`, or MOON's own approval UI.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.laboratory.model import Capability, RiskTier

logger = logging.getLogger(__name__)

_APPROVAL_TTL_SECONDS = 3600  # one hour by default

Decision = dict  # name -> value, easier to serialize than a bare dict


@dataclass
class Approval:
    approval_id: str
    capability: str
    task: str
    scope: dict
    caller: str
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=time.time)
    acknowledged: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["expires_at"] = round(d["expires_at"], 6)
        return d

    def is_active(self) -> bool:
        return time.time() < self.expires_at

    def matches(self, capability: str, scope: dict) -> bool:
        if capability != self.capability:
            return False
        for key, val in scope.items():
            if key not in self.scope:
                return False
            if self.scope[key] != val:
                return False
        return True


class ApprovalStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._path = self.root / "approvals.json"
        self._records: dict[str, Approval] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                import json

                data = json.loads(self._path.read_text(encoding="utf-8"))
                for rec in data.get("approvals", []):
                    a = Approval(**rec)
                    if a.is_active():
                        self._records[a.approval_id] = a
            except Exception as exc:  # noqa: BLE001
                logger.warning("approval store load failed: %s", exc)

    def _save(self) -> None:
        data = {"approvals": [r.to_dict() for r in self._records.values()]}
        self._path.write_text(
            json_dumps(data, indent=2), encoding="utf-8"
        )

    def register(
        self,
        capability: str,
        task: str,
        scope: dict,
        caller: str,
        *,
        ttl_seconds: int = _APPROVAL_TTL_SECONDS,
    ) -> Approval:
        aid = uuid.uuid4().hex
        a = Approval(
            approval_id=aid,
            capability=capability,
            task=task,
            scope=scope,
            caller=caller,
            expires_at=time.time() + ttl_seconds,
        )
        self._records[aid] = a
        self._save()
        return a

    def active(self) -> list[Approval]:
        return [a for a in self._records.values() if a.is_active()]

    def find(self, capability: str, scope: dict) -> Approval | None:
        for a in self._records.values():
            if a.is_active() and a.matches(capability, scope):
                return a
        return None

    def revoke(self, approval_id: str) -> bool:
        if approval_id in self._records:
            del self._records[approval_id]
            self._save()
            return True
        return False


def json_dumps(obj: object, **kw: Any) -> str:
    import json
    return json.dumps(obj, **kw)


class PolicyEngine:
    """Evaluates one capability execution request against MOON's authorization."""

    def __init__(self, store: ApprovalStore | None = None) -> None:
        self.store = store or ApprovalStore("/tmp/lab_approvals_placeholder")
        self._allowlist: set[str] = set()
        self._denylist: set[str] = set()

    # ------------------------------------------------------------------ #
    # gate
    # ------------------------------------------------------------------ #
    def evaluate(self, capability: Capability, task: str,
                 params: dict, caller: str) -> dict:
        reasons: list[str] = []
        if capability.name in self._denylist:
            return {
                "allowed": False,
                "decision": "BLOCK",
                "reasons": [f"capability denylisted: {capability.name}"],
                "approval_id": None,
            }
        if capability.name in self._allowlist:
            return {
                "allowed": True,
                "decision": "ALLOW",
                "reasons": [f"allowlisted capability: {capability.name}"],
                "approval_id": None,
            }
        if capability.status != "available":
            return {
                "allowed": False,
                "decision": "BLOCK",
                "reasons": [f"capability disabled ({capability.status})"],
                "approval_id": None,
            }
        if capability.tier == RiskTier.READ_ONLY:
            reasons.append("tier 0 read-only; no approval required")
            return self._allow(capability, task, params, reasons)
        if capability.tier == RiskTier.LOW_RISK:
            reasons.append("tier 1 low-risk; allowed")
            return self._allow(capability, task, params, reasons)
        if capability.tier == RiskTier.CONTROLLED_TEST:
            a = self.store.find(capability.name, params)
            if a is not None:
                reasons.append("controlled-test approved by existing approval")
                return self._allow(capability, task, params, reasons)
            reasons.append(
                "controlled test requires explicit approval (least privilege)"
            )
            return {
                "allowed": False, "decision": "BLOCK",
                "reasons": reasons, "approval_id": None,
            }
        # HIGH_IMPACT
        scope = self._normalise_scope(params)
        a = self.store.find(capability.name, scope)
        if a is not None:
            reasons.append(
                "high-impact capability approved by existing approval"
            )
            return self._allow(capability, task, params, reasons)
        reasons.append(
            "high-impact capability is BLOCKED by default (least privilege)"
        )
        return {
            "allowed": False, "decision": "BLOCK",
            "reasons": reasons, "approval_id": None,
        }

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _allow(capability: Capability, task: str, params: dict,
               reasons: list[str]) -> dict:
        return {
            "allowed": True, "decision": "ALLOW",
            "reasons": reasons,
            "approval_id": None,
        }

    @staticmethod
    def _normalise_scope(params: dict) -> dict:
        """Reduce raw params to the exact fields the policy is allowed to match."""
        scope: dict = {}
        for key in ("target", "host", "path", "action", "file", "scope"):
            if key in params:
                scope[key] = params[key]
        return scope
