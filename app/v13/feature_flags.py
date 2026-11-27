"""Opt-in feature flags with dependency checks, history and rollback.

Additive by design: a capability absent from the store is DISABLED, so adding
this module cannot silently enable or change existing MOON behaviour.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class FlagState(str, Enum):
    DISABLED = "disabled"
    EXPERIMENTAL = "experimental"
    BETA = "beta"
    ENABLED = "enabled"


def _default_path() -> Path:
    root = Path(os.environ.get("MOON_STATE_DIR", Path(__file__).resolve().parents[2] / ".moon"))
    return root / "v13" / "feature_flags.json"


@dataclass
class FeatureFlag:
    name: str
    state: FlagState = FlagState.DISABLED
    description: str = ""
    owner: str = "MOON"
    version: str = "1.0.0"
    dependencies: tuple[str, ...] = ()
    requires_approval: bool = False
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        d["dependencies"] = list(self.dependencies)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FeatureFlag":
        known = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        kwargs = {k: v for k, v in data.items() if k in known}
        kwargs["state"] = FlagState(str(kwargs.get("state", FlagState.DISABLED.value)))
        kwargs["dependencies"] = tuple(kwargs.get("dependencies") or ())
        return cls(**kwargs)

    @property
    def available(self) -> bool:
        return self.state is not FlagState.DISABLED


class FeatureFlagStore:
    """Thread-safe, file-backed flag store. No global mutable state."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else _default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._flags: dict[str, FeatureFlag] = {}
        self._history: dict[str, list[dict[str, Any]]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for name, raw in (data.get("flags") or {}).items():
            try:
                self._flags[name] = FeatureFlag.from_dict({**raw, "name": name})
            except (TypeError, ValueError):
                continue
        for name, entries in (data.get("history") or {}).items():
            self._history[name] = list(entries)

    def _save(self) -> None:
        payload = {
            "version": 1,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "flags": {n: f.to_dict() for n, f in self._flags.items()},
            "history": self._history,
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    def register(self, flag: FeatureFlag) -> FeatureFlag:
        with self._lock:
            existing = self._flags.get(flag.name)
            if existing is None:
                flag.updated_at = flag.updated_at or self._now()
                self._flags[flag.name] = flag
                self._save()
                return flag
            return existing

    @staticmethod
    def _now() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def get(self, name: str) -> FeatureFlag:
        return self._flags.get(name, FeatureFlag(name=name, state=FlagState.DISABLED))

    def set_state(self, name: str, state: FlagState | str, *, actor: str = "MOON") -> FeatureFlag:
        target = state if isinstance(state, FlagState) else FlagState(str(state))
        with self._lock:
            flag = self.get(name)
            if flag.state is target:
                return flag
            self._history.setdefault(name, []).append(
                {"from": flag.state.value, "to": target.value, "actor": actor, "at": self._now()}
            )
            updated = FeatureFlag.from_dict({**flag.to_dict(), "state": target.value,
                                             "updated_at": self._now()})
            self._flags[name] = updated
            self._save()
            return updated

    def enable(self, name: str, *, actor: str = "MOON") -> FeatureFlag:
        return self.set_state(name, FlagState.ENABLED, actor=actor)

    def disable(self, name: str, *, actor: str = "MOON") -> FeatureFlag:
        return self.set_state(name, FlagState.DISABLED, actor=actor)

    def is_enabled(self, name: str) -> bool:
        """Environment override wins; disabled-by-default otherwise."""
        env_key = "MOON_FLAG_" + name.replace("-", "_").replace(".", "_").upper()
        if env_key in os.environ:
            return os.environ[env_key].strip().lower() in {"1", "true", "yes", "on"}
        flag = self.get(name)
        if not flag.available:
            return False
        missing = [d for d in flag.dependencies if not self.get(d).available]
        return not missing

    def unmet_dependencies(self, name: str) -> list[str]:
        return [d for d in self.get(name).dependencies if not self.get(d).available]

    def history(self, name: str) -> list[dict[str, Any]]:
        return list(self._history.get(name, []))

    def rollback(self, name: str, *, actor: str = "MOON") -> FeatureFlag | None:
        entries = self._history.get(name) or []
        if not entries:
            return None
        previous = FlagState(str(entries[-1]["from"]))
        return self.set_state(name, previous, actor=actor)

    def all(self) -> list[FeatureFlag]:
        return [self._flags[k] for k in sorted(self._flags)]
