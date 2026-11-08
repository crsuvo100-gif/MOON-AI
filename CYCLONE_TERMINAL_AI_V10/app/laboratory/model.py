"""Laboratory domain model.

Pydantic is avoided here on purpose: the laboratory must import and start even
when optional dependencies or network configuration are degraded, so plain
mutable dataclasses + to_dict/from_dict keep the module import-safe.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.laboratory.lifecycle import LifecycleState


class RiskTier(int, Enum):
    """Risk tiers. MOON follows default-deny: only tier 0 is auto-allowed."""
    READ_ONLY = 0
    LOW_RISK = 1
    CONTROLLED_TEST = 2
    HIGH_IMPACT = 3

    @property
    def label(self) -> str:
        return {
            0: "read-only",
            1: "low-risk",
            2: "controlled-testing",
            3: "high-impact",
        }.get(int(self), "unknown")


@dataclass
class Capability:
    """A single laboratory capability with its authorization profile."""
    name: str
    category: str                      # e.g. "local-analysis", "network", "policy"
    title: str
    description: str
    tier: RiskTier = RiskTier.READ_ONLY
    required_scope: tuple[str, ...] = ()
    parameters: dict[str, Any] = field(default_factory=dict)
    dependencies: tuple[str, ...] = field(default_factory=tuple)
    adapter: str = ""                  # key into app.laboratory.adapters
    status: str = "available"          # available | disabled | blocked
    health: str = "unknown"            # unknown | healthy | degraded | unhealthy
    source: str = "bundled"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "title": self.title,
            "description": self.description,
            "tier": int(self.tier),
            "tier_label": self.tier.label,
            "required_scope": list(self.required_scope),
            "parameters": self.parameters,
            "dependencies": list(self.dependencies),
            "adapter": self.adapter,
            "status": self.status,
            "health": self.health,
            "source": self.source,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Capability":
        return cls(**data)


@dataclass
class ExecutionResult:
    """Result of executing a capability through the laboratory."""
    capability: str
    task: str
    params: dict[str, Any]
    adapter: str
    decision: dict[str, Any]           # policy decision (ALLOW/BLOCK/etc.)
    output: str = ""
    validated: bool = False
    error: str = ""
    duration_s: float = 0.0
    audit_id: str = ""
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "task": self.task,
            "params": self.params,
            "adapter": self.adapter,
            "decision": self.decision,
            "output": self.output,
            "validated": self.validated,
            "error": self.error,
            "duration_s": round(self.duration_s, 6),
            "audit_id": self.audit_id,
            "errors": self.errors,
        }


@dataclass
class AuditEvent:
    """Redaction-safe audit record written to the laboratory audit log."""
    event_id: str
    ts: float = field(default_factory=time.time)
    kind: str = ""                     # execute | approve | deny | lifecycle | error
    capability: str = ""
    scope: str = ""                    # caller e.g. "api" | "orchestrator" | "console"
    params: dict[str, Any] = field(default_factory=dict)
    decision: dict[str, Any] = field(default_factory=dict)
    detail: str = ""
    sanitised: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["ts"] = round(d["ts"], 6) if isinstance(d["ts"], float) else d["ts"]
        return d


def asdict(obj: Any) -> dict[str, Any]:
    """Minimal dataclass introspection compatible across Python 3.10-3.14."""
    return {f.name: getattr(obj, f.name) for f in obj.__dataclass_fields__.values()}
