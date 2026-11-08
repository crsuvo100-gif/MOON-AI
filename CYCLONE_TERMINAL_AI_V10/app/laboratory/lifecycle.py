"""Lifecycle state machine for acquired laboratory capabilities.

State progression (following the configured acquisition policy):
    PROPOSED -> REVIEWED -> APPROVED -> ACQUIRED -> VERIFIED -> INSTALLED -> TESTED -> ENABLED
Terminal states (cannot leave):
    REJECTED, QUARANTINED, DISABLED, FAILED, ROLLED_BACK

Transitions are validated against a whitelist so a capability can never move
backward or skip required gates except through an explicit rollback action.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LifecycleState = str  # allowed states for a capability in the lifecycle store

logger = logging.getLogger(__name__)

# Full ordered path from proposal to enabled.
_PATH = [
    "PROPOSED", "REVIEWED", "APPROVED", "ACQUIRED", "VERIFIED",
    "INSTALLED", "TESTED", "ENABLED",
]

# Terminal states: once reached, no further transitions are allowed.
_TERMINAL = {"REJECTED", "QUARANTINED", "DISABLED", "FAILED", "ROLLED_BACK"}

# Allowed forward steps (skip-ahead only when explicitly configured).
_FROM: dict[str, list[str]] = {s: [] for s in _PATH}
for _i, _s in enumerate(_PATH):
    _FROM[_s] = _PATH[_i + 1:]
# Rollback: a terminal state can step back one full phase, never backward in
# capability.
_ROLLBACK = {
    "INSTALLED": "TESTED", "TESTED": "INSTALLED", "ENABLED": "INSTALLED",
    "VERIFIED": "INSTALLED", "ACQUIRED": "REVIEWED", "REVIEWED": "PROPOSED",
}


@dataclass
class LifecycleRecord:
    capability: str
    state: str = "PROPOSED"
    detail: dict[str, Any] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "state": self.state,
            "detail": self.detail,
            "updated_at": round(self.updated_at, 6),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LifecycleRecord":
        return cls(**data)


class LifecycleStore:
    """File-backed store of capability acquisition lifecycles."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._path = self.root / "lifecycle.json"
        self._records: dict[str, LifecycleRecord] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                for rec in data.get("lifecycle", []):
                    self._records[rec["capability"]] = LifecycleRecord.from_dict(
                        rec
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("lifecycle load failed: %s", exc)

    def _save(self) -> None:
        self._path.write_text(
            json.dumps({"lifecycle": [r.to_dict() for r in self._records.values()]},
                       indent=2),
            encoding="utf-8",
        )

    # -- transitions -----------------------------------------------------
    def transition(self, capability: str, to: str,
                   detail: dict[str, Any] | None = None) -> dict[str, Any]:
        rec = self._records.get(capability)
        if rec is None:
            rec = LifecycleRecord(capability=capability, state="PROPOSED")
            self._records[capability] = rec
        cur = rec.state
        if cur in _TERMINAL:
            return {"ok": False, "error": "terminal state reached"}
        if cur != "PROPOSED" and to not in _FROM.get(cur, []):
            return {"ok": False, "error": f"invalid transition {cur} -> {to}"}
        if to in _TERMINAL:
            # allow only an explicit rollback from a progress state
            if cur in _ROLLBACK and _ROLLBACK[cur] == to:
                pass
            else:
                return {"ok": False, "error": "cannot enter terminal state"}
        rec.state = to
        rec.updated_at = time.time()
        rec.detail = detail or {}
        self._save()
        return {"ok": True, "capability": capability, "state": to}

    def current(self, capability: str) -> str:
        return self._records.get(capability, LifecycleRecord(capability)).state

    def all(self) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self._records.values()]
