"""Privacy-safe structured execution tracing for MOON V13."""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class EventKind(str, Enum):
    TASK = "task"
    AGENT = "agent"
    MODEL = "model"
    TOOL = "tool"
    APPROVAL = "approval"
    ERROR = "error"
    RETRY = "retry"
    RESULT = "result"


_SECRET_KEY = re.compile(r"(?i)(api[_-]?key|token|password|passwd|secret|authorization|credential)")
_SECRET_VALUE = re.compile(r"(sk-[A-Za-z0-9]{16,}|gh[pousr]_[A-Za-z0-9]{20,})")


def redact(value: Any) -> Any:
    """Recursively redact secret-bearing keys and well-known secret tokens."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if _SECRET_KEY.search(str(key)):
                out[key] = "[REDACTED]"
            else:
                out[key] = redact(item)
        return out
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return _SECRET_VALUE.sub("[REDACTED]", value)
    return value


@dataclass
class Event:
    event_id: str
    trace_id: str
    kind: EventKind
    name: str
    at: str
    duration_ms: float = 0.0
    status: str = "ok"
    actor: str = "MOON"
    task_id: str = ""
    agent_id: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id, "trace_id": self.trace_id,
            "kind": self.kind.value, "name": self.name, "at": self.at,
            "duration_ms": round(self.duration_ms, 3), "status": self.status,
            "actor": self.actor, "task_id": self.task_id, "agent_id": self.agent_id,
            "data": redact(self.data),
        }


class Trace:
    """Append-only, JSONL-persisted trace. Records IDs, durations and outcomes."""

    def __init__(self, path: str | Path | None = None, *, trace_id: str | None = None) -> None:
        import os
        root = Path(os.environ.get("MOON_STATE_DIR", Path(__file__).resolve().parents[2] / ".moon"))
        self.path = Path(path) if path is not None else root / "v13" / "trace.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.trace_id = trace_id or uuid.uuid4().hex[:16]
        self._lock = threading.RLock()
        self.events: list[Event] = []

    @staticmethod
    def _now() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def emit(self, kind: EventKind | str, name: str, *, data: dict[str, Any] | None = None,
             duration_ms: float = 0.0, status: str = "ok", actor: str = "MOON",
             task_id: str = "", agent_id: str = "") -> Event:
        event = Event(
            event_id=uuid.uuid4().hex[:12], trace_id=self.trace_id,
            kind=kind if isinstance(kind, EventKind) else EventKind(str(kind)),
            name=name, at=self._now(), duration_ms=duration_ms, status=status,
            actor=actor, task_id=task_id, agent_id=agent_id, data=dict(data or {}),
        )
        with self._lock:
            self.events.append(event)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")
        return event

    def span(self, kind: EventKind | str, name: str, **kwargs: Any) -> "_Span":
        return _Span(self, kind, name, **kwargs)

    def summary(self) -> dict[str, Any]:
        by_kind: dict[str, int] = {}
        errors = 0
        total_ms = 0.0
        for event in self.events:
            by_kind[event.kind.value] = by_kind.get(event.kind.value, 0) + 1
            errors += int(event.status == "error" or event.kind is EventKind.ERROR)
            total_ms += event.duration_ms
        return {"trace_id": self.trace_id, "events": len(self.events),
                "by_kind": by_kind, "errors": errors, "duration_ms": round(total_ms, 3)}


class _Span:
    def __init__(self, trace: Trace, kind: EventKind | str, name: str, **kwargs: Any) -> None:
        self.trace, self.kind, self.name, self.kwargs = trace, kind, name, kwargs
        self.start = time.perf_counter()
        self.status = "ok"
        self.data: dict[str, Any] = dict(kwargs.pop("data", {}) or {})

    def __enter__(self) -> "_Span":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        if exc is not None:
            self.status = "error"
            self.data["error_type"] = type(exc).__name__
        self.trace.emit(self.kind, self.name, data=self.data, status=self.status,
                        duration_ms=(time.perf_counter() - self.start) * 1000,
                        **{k: v for k, v in self.kwargs.items()})
        return False
