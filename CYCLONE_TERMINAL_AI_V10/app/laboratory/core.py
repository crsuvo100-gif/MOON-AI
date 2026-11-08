"""Core laboratory runtime.

MOON drives capabilities through `get_laboratory()` and `Laboratory.execute()`.
The laboratory is a pure Python subsystem with no Hermes dependency; it
initializes lazily and shuts down cleanly. It never fetches models, contacts
third parties, or mutates user data on its own.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.laboratory.adapters import AdapterResult
from app.laboratory.audit import AuditStore
from app.laboratory.lifecycle import LifecycleStore
from app.laboratory.model import Capability, ExecutionResult
from app.laboratory.policy import ApprovalStore, PolicyEngine
from app.laboratory.registry import LaboratoryRegistry

logger = logging.getLogger(__name__)


def _default_lab_root() -> Path:
    return Path.home() / "MOON_lab"


def _discover_lab_root() -> Path:
    """Honor MOON's configuration for the laboratory root."""
    try:
        from app.runtime import config as _cfg  # type: ignore
        candidate = _cfg.get("laboratory.root")
        if candidate:
            p = Path(candidate)
            if p.is_dir():
                return p
    except Exception:  # noqa: BLE001 - config is optional
        pass
    return _default_lab_root()


class Laboratory:
    """The authoritative laboratory runtime for MOON.

    Built-in capabilities are registered at startup. Optional capability
    sources (e.g. approved plugin packs) can be added later through
    register_capability. All execution is policy-gated and auditable.
    """

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root else _discover_lab_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self.data_dir = self.root / "data"
        self.approvals_file = self.data_dir / "approvals.json"
        self.capability_dir = self.root / "capabilities"
        self.audit_file = self.root / "audit.jsonl"

        self.approval_store = ApprovalStore(self.data_dir)
        self.lifecycle_store = LifecycleStore(self.capability_dir)
        self.registry = LaboratoryRegistry(self.root)
        self.policy_engine = PolicyEngine(self.approval_store)
        self.audit_store = AuditStore(self.audit_file)
        self._started = False

    # -- lifecycle -----------------------------------------------------
    def startup(self) -> dict:
        if self._started:
            return {"ok": True, "state": "already_started"}
        self._started = True
        logger.info(
            "laboratory startup: root=%s caps=%d approvals=%d",
            self.root,
            len(self.registry.all()),
            len(self.approval_store.active()),
        )
        self.audit_store.log(
            "startup", {
                "root": str(self.root),
                "capabilities": len(self.registry.all()),
                "disk_bytes": self.root.stat().st_size,
            }
        )
        return {
            "ok": True,
            "state": "started",
            "root": str(self.root),
            "capabilities": len(self.registry.all()),
            "approvals": len(self.approval_store.active()),
        }

    def shutdown(self) -> dict:
        self._started = False
        logger.info(
            "laboratory shutdown: approvals=%d",
            len(self.approval_store.active()),
        )
        return {"ok": True, "state": "shutdown"}

    # -- capability registry -------------------------------------------------
    def get_capability(self, name: str) -> Capability | None:
        return self.registry.get(name)

    def list_capabilities(self) -> list[Capability]:
        return self.registry.all()

    def list_enabled(self) -> list[Capability]:
        return [c for c in self.registry.all() if c.status == "available"]

    def register_capability(self, capability: Capability) -> Capability:
        self.registry._caps[capability.name.lower()] = capability
        self.lifecycle_store.transition(
            capability.name, "ENABLED", {"source": "dynamic_registration"}
        )
        return capability

    def by_tier(self, tier: int) -> list[Capability]:
        return self.registry.by_tier(tier)

    def counts(self) -> dict:
        return self.registry.counts()

    # -- lifecycle state -----------------------------------------------------
    def lifecycle_state(self, capability: str) -> str:
        return self.lifecycle_store.current(capability)

    def lifecycle_transition(
        self, capability: str, to: str, detail: dict[str, Any] | None = None
    ) -> dict:
        return self.lifecycle_store.transition(capability, to, detail)

    # -- policy -----------------------------------------------------------------
    def evaluate(self, capability: Capability, task: str,
                 params: dict, caller: str) -> dict:
        return self.policy_engine.evaluate(capability, task, params, caller)

    def create_approval(
        self, capability: str, task: str, scope: dict, caller: str,
        ttl_seconds: int | None = None,
    ) -> dict:
        ttl = ttl_seconds or 3600
        approval = self.approval_store.register(
            capability=capability, task=task, scope=scope, caller=caller,
            ttl_seconds=ttl,
        )
        self.audit_store.log(
            "approve", {
                "approval_id": approval.approval_id,
                "capability": capability,
                "caller": caller,
                "expires_at": approval.expires_at,
            }
        )
        return {"ok": True, "approval": approval.to_dict()}

    def find_approval(self, capability: str, scope: dict) -> dict:
        a = self.approval_store.find(capability, scope)
        if a is None:
            return {"ok": False, "error": "no active approval found"}
        return {"ok": True, "approval": a.to_dict()}

    def revoke_approval(self, approval_id: str) -> dict:
        if not self.approval_store.revoke(approval_id):
            return {"ok": False, "error": "approval not found"}
        self.audit_store.log("revoke", {"approval_id": approval_id})
        return {"ok": True, "revoked": approval_id}

    # -- execution ---------------------------------------------------------------
    def execute(self, capability: str, task: str, params: dict | None = None,
                caller: str = "api") -> ExecutionResult:
        """Policy-gated, audited execution of one laboratory capability."""
        if not self._started:
            return ExecutionResult(
                capability=capability,
                task=task,
                params=params or {},
                adapter="unknown",
                decision={"allowed": False, "decision": "BLOCK",
                          "reasons": ["laboratory not started"]},
                error="laboratory not started",
            )
        cap = self.get_capability(capability)
        if cap is None:
            return ExecutionResult(
                capability=capability, task=task, params=params or {},
                adapter="unknown",
                decision={"allowed": False, "decision": "BLOCK",
                          "reasons": ["capability not registered"]},
                error="capability not registered",
            )
        start = time.monotonic()
        decision = self.evaluate(cap, task, params or {}, caller)
        out = AdapterResult(output="", validated=False, error="")
        if not decision.get("allowed", False):
            self.audit_store.log(
                "deny", {
                    "capability": cap.name, "decision": decision,
                    "reasons": decision.get("reasons", []),
                    "caller": caller,
                }
            )
            return ExecutionResult(
                capability=cap.name, task=task,
                params=params or {}, adapter=cap.adapter,
                decision=decision,
                error="; ".join(decision.get("reasons", [])) or "denied",
            )
        try:
            adapter_func = _adapters.get(cap.adapter)
            if adapter_func is None:
                raise RuntimeError(f"adapter {cap.adapter!r} not found")
            out = adapter_func(params or {})
        except Exception as exc:  # noqa: BLE001
            self.audit_store.log(
                "error", {"capability": cap.name, "error": repr(exc)})
            return ExecutionResult(
                capability=cap.name, task=task,
                params=params or {}, adapter=cap.adapter,
                decision=decision,
                error=f"adapter failed: {exc!r}",
            )
        final = ExecutionResult(
            capability=cap.name, task=task,
            params=params or {}, adapter=cap.adapter,
            decision=decision,
            output=out.output,
            validated=out.validated,
            duration_s=time.monotonic() - start,
            errors=out.error and [out.error] or [],
        )
        final.audit_id = self.audit_store.log(
            "execute", {
                "capability": cap.name, "decision": decision,
                "adapter": cap.adapter, "output_chars": len(out.output),
                "validated": out.validated,
            }
        )
        if out.validated:
            self.lifecycle_transition(cap.name, "ENABLED", {
                "last_run": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
        return final


# Adapter implementations map to functions above. The policy engine and audit
# layer resolve them lazily so each adapter is only imported when used.
def _local_inventory_adapter_impl(params: dict[str, Any]) -> AdapterResult:
    from app.laboratory.adapters import local_inventory_adapter
    return local_inventory_adapter(params)


def _local_env_probe_adapter_impl(params: dict[str, Any]) -> AdapterResult:
    from app.laboratory.adapters import local_env_probe_adapter
    return local_env_probe_adapter(params)


def _echo_adapter_impl(params: dict[str, Any]) -> AdapterResult:
    from app.laboratory.adapters import echo_adapter
    return echo_adapter(params)


def _redact_adapter_impl(params: dict[str, Any]) -> AdapterResult:
    from app.laboratory.adapters import redact_adapter
    return redact_adapter(params)


def _loopback_probe_adapter_impl(params: dict[str, Any]) -> AdapterResult:
    from app.laboratory.adapters import loopback_probe_adapter
    return loopback_probe_adapter(params)


def _policy_echo_adapter_impl(params: dict[str, Any]) -> AdapterResult:
    from app.laboratory.adapters import policy_echo_adapter
    return policy_echo_adapter(params)


# Map adapter names to functions. The policy engine and audit layer never
# import adapter bodies here; they are resolved lazily so that a missing
# adapter is a configuration error, not a startup failure.
_adapters: dict[str, Callable[[dict[str, Any]], AdapterResult]] = {
    "local_inventory": _local_inventory_adapter_impl,
    "local_env_probe": _local_env_probe_adapter_impl,
    "echo": _echo_adapter_impl,
    "redact": _redact_adapter_impl,
    "loopback_probe": _loopback_probe_adapter_impl,
    "policy_echo": _policy_echo_adapter_impl,
}
