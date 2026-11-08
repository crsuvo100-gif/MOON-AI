"""Audit record store for the laboratory.

All execution, approval, and lifecycle events are appended as JSONL to a
redaction-safe audit log. The log intentionally never serializes raw secrets:
adapter adapters must not emit them, and the free-form text that is stored is
already the `sanitised` field.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class AuditStore:
    """Append-only, JSONL audit log that never carries secrets."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, kind: str, payload: dict[str, Any]) -> str:
        event_id = uuid.uuid4().hex
        event: dict[str, Any] = {
            "event_id": event_id,
            "ts": round(time.time(), 6),
            "kind": kind,
            "payload": payload,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        logger.info("laboratory audit: %s/%s", kind, event_id)
        return event_id
