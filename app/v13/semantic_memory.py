"""Deterministic, permission-aware semantic retrieval over governed memory."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Iterable

from .memory_governance import GovernanceRecord, Sensitivity, Validation

_TOKEN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class MemoryHit:
    record_id: str
    score: float
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"record_id": self.record_id, "score": round(self.score, 4),
                "reasons": list(self.reasons)}


def tokenize(text: str) -> set[str]:
    return set(_TOKEN.findall((text or "").lower()))


class SemanticMemoryRetriever:
    """Lexical-semantic scoring with trust, recency and sensitivity controls.

    Accepts any object exposing ``all_records()`` returning GovernanceRecord-like
    objects, so it layers over the existing memory system without replacing it.
    """

    def __init__(self, store: Any, *, lexical_weight: float = 0.6,
                 trust_weight: float = 0.2, recency_weight: float = 0.2) -> None:
        self.store = store
        self.lexical_weight = lexical_weight
        self.trust_weight = trust_weight
        self.recency_weight = recency_weight

    @staticmethod
    def _age_score(record: GovernanceRecord, now: float) -> float:
        stamp = record.created_at or record.last_accessed
        try:
            parsed = time.mktime(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ"))
        except (TypeError, ValueError):
            return 0.5
        age_days = max(0.0, (now - parsed) / 86400.0)
        return max(0.0, 1.0 - age_days / 365.0)

    def retrieve(self, query: str, *, limit: int = 5, min_confidence: float = 0.0,
                 allow_sensitive: bool = False,
                 sensitivities: Iterable[Sensitivity] | None = None,
                 now: float | None = None) -> list[MemoryHit]:
        q_tokens = tokenize(query)
        if not q_tokens:
            return []
        now = now if now is not None else time.time()
        allowed = set(sensitivities) if sensitivities is not None else None
        hits: list[MemoryHit] = []
        for rec in self.store.all_records():
            if float(rec.confidence) < min_confidence:
                continue
            if rec.validation is Validation.CONTRADICTED or rec.superseded_by:
                continue
            if rec.expires_at and rec.expires_at <= time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)):
                continue
            if not allow_sensitive and rec.sensitivity in {Sensitivity.SECRET, Sensitivity.CONFIDENTIAL,
                                                            Sensitivity.PERSONAL}:
                continue
            if allowed is not None and rec.sensitivity not in allowed:
                continue
            content_tokens = tokenize(rec.content) | tokenize(" ".join(rec.tags))
            overlap = q_tokens & content_tokens
            if not overlap:
                continue
            lexical = len(overlap) / max(1, len(q_tokens))
            trust = float(rec.confidence) * (1.0 if rec.validation is Validation.VERIFIED else 0.7)
            recency = self._age_score(rec, now)
            score = (self.lexical_weight * lexical + self.trust_weight * trust
                     + self.recency_weight * recency)
            reasons = ("lexical_overlap", "confidence", "recency")
            hits.append(MemoryHit(rec.record_id, score, reasons))
        hits.sort(key=lambda h: (-h.score, h.record_id))
        return hits[:max(0, limit)]
