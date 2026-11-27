"""Provenance, sensitivity and correction controls for MOON memory writes."""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


class Sensitivity(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    PERSONAL = "personal"
    SECRET = "secret"


class Validation(str, Enum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    CONTRADICTED = "contradicted"


_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(api[_-]?key|token|password|passwd|secret|private[_-]?key|authorization)\b\s*[:=]\s*\S+"),
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
)


def contains_secret(value: str) -> bool:
    return any(pattern.search(value or "") for pattern in _SECRET_PATTERNS)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class GovernanceRecord:
    record_id: str
    content: str
    source: str
    source_type: str = "user"           # user | agent | retrieval | tool | document
    sensitivity: Sensitivity = Sensitivity.INTERNAL
    confidence: float = 0.5
    validation: Validation = Validation.UNVERIFIED
    provenance: dict[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    created_at: str = ""
    expires_at: str = ""
    last_accessed: str = ""
    access_count: int = 0
    superseded_by: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["sensitivity"] = self.sensitivity.value
        d["validation"] = self.validation.value
        d["tags"] = list(self.tags)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GovernanceRecord":
        known = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        kw = {k: v for k, v in data.items() if k in known}
        kw["sensitivity"] = Sensitivity(str(kw.get("sensitivity", Sensitivity.INTERNAL.value)))
        kw["validation"] = Validation(str(kw.get("validation", Validation.UNVERIFIED.value)))
        kw["tags"] = tuple(kw.get("tags") or ())
        return cls(**kw)


class GovernanceStore:
    """File-backed, additive memory governance layer.

    Never accepts SECRET content into durable memory; records carry provenance
    and can be corrected without erasing the superseded fact.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        import os
        root = Path(os.environ.get("MOON_STATE_DIR", Path(__file__).resolve().parents[2] / ".moon"))
        self.path = Path(path) if path is not None else root / "v13" / "memory_governance.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._records: dict[str, GovernanceRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for key, raw in (data.get("records") or {}).items():
            try:
                self._records[key] = GovernanceRecord.from_dict({**raw, "record_id": key})
            except (TypeError, ValueError):
                continue

    def _save(self) -> None:
        payload = {
            "version": 1,
            "records": {k: r.to_dict() for k, r in self._records.items()},
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    def add(
        self,
        content: str,
        *,
        source: str,
        source_type: str = "user",
        sensitivity: Sensitivity = Sensitivity.INTERNAL,
        confidence: float = 0.5,
        provenance: dict[str, Any] | None = None,
        tags: Iterable[str] = (),
        ttl_seconds: int | None = None,
        record_id: str | None = None,
    ) -> GovernanceRecord:
        if sensitivity is Sensitivity.SECRET or contains_secret(content or ""):
            raise ValueError("refusing to persist secret material into memory")
        if not 0.0 <= float(confidence) <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        with self._lock:
            rid = record_id or uuid.uuid4().hex[:16]
            if rid in self._records:
                raise ValueError("duplicate record id")
            rec = GovernanceRecord(
                record_id=rid,
                content=content,
                source=source,
                source_type=source_type,
                sensitivity=sensitivity,
                confidence=float(confidence),
                provenance=dict(provenance or {}),
                tags=tuple(tags),
                created_at=_now(),
                expires_at=(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(time.time()) + ttl_seconds))
                            if ttl_seconds else ""),
                last_accessed=_now(),
            )
            self._records[rid] = rec
            self._save()
            return rec

    def get(self, record_id: str) -> GovernanceRecord | None:
        rec = self._records.get(record_id)
        if rec is not None:
            rec.access_count += 1
            rec.last_accessed = _now()
        return rec

    def all_records(self) -> list[GovernanceRecord]:
        return list(self._records.values())

    def correct(self, record_id: str, new_content: str, *, reason: str,
                confidence: float = 0.9, source: str = "correction") -> GovernanceRecord:
        old = self._records.get(record_id)
        if old is None:
            raise KeyError(record_id)
        with self._lock:
            replacement = self.add(
                new_content,
                source=source,
                source_type="correction",
                sensitivity=old.sensitivity,
                confidence=confidence,
                provenance={"corrects": record_id, "reason": reason},
                tags=old.tags,
            )
            old.validation = Validation.CONTRADICTED
            old.superseded_by = replacement.record_id
            self._save()
            return replacement

    def verify(self, record_id: str) -> None:
        rec = self._records.get(record_id)
        if rec is None:
            raise KeyError(record_id)
        rec.validation = Validation.VERIFIED
        self._save()

    def expire(self, record_id: str) -> bool:
        with self._lock:
            rec = self._records.pop(record_id, None)
            if rec is None:
                return False
            self._save()
            return True

    def purge_expired(self) -> list[str]:
        now = _now()
        expired = [k for k, r in self._records.items() if r.expires_at and r.expires_at <= now]
        for key in expired:
            self._records.pop(key, None)
        if expired:
            self._save()
        return expired

    def export(self, *, redact: bool = True) -> dict[str, Any]:
        """Export records; confidential/personal text is redacted by default."""
        out = {}
        for key, rec in self._records.items():
            d = rec.to_dict()
            if redact and rec.sensitivity in {Sensitivity.CONFIDENTIAL, Sensitivity.PERSONAL}:
                d["content"] = "[REDACTED]"
            out[key] = d
        return {"version": 1, "records": out}

    def stats(self) -> dict[str, int]:
        result: dict[str, int] = {s.value: 0 for s in Sensitivity}
        for rec in self._records.values():
            result[rec.sensitivity.value] += 1
        result["total"] = len(self._records)
        return result
