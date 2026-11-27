"""Cost-, latency-, privacy- and capability-aware model routing (additive)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Workload(str, Enum):
    REASONING = "reasoning"
    CODING = "coding"
    SECURITY = "security"
    VISION = "vision"
    CONTEXT = "context"
    LATENCY = "latency"
    COST = "cost"
    PRIVACY = "privacy"
    LOCAL_RESOURCES = "local_resources"
    QUALITY = "quality"


@dataclass(frozen=True)
class ModelCandidate:
    name: str
    provider: str
    capabilities: frozenset[str]
    cost_per_1k: float = 0.0
    latency_ms: int = 1000
    quality: float = 0.5
    context_window: int = 8192
    local: bool = False
    available: bool = True

    def supports(self, workload: Workload) -> bool:
        required = {
            Workload.VISION: "vision",
            Workload.CODING: "coding",
            Workload.SECURITY: "reasoning",
            Workload.REASONING: "reasoning",
        }.get(workload)
        return required is None or required in self.capabilities


@dataclass
class RoutingDecision:
    selected: ModelCandidate | None
    fallbacks: list[ModelCandidate] = field(default_factory=list)
    reason: str = ""
    at: str = ""


class CostAwareRouter:
    """Scores explicit candidate metadata; never calls a provider itself."""

    _CAP_WEIGHTS: dict[Workload, float] = {
        Workload.REASONING: 0.5, Workload.CODING: 0.5, Workload.SECURITY: 0.5,
        Workload.VISION: 0.6, Workload.CONTEXT: 0.15, Workload.LATENCY: 0.2,
        Workload.COST: 0.3, Workload.PRIVACY: 0.3,
        Workload.LOCAL_RESOURCES: 0.25, Workload.QUALITY: 0.5,
    }

    def __init__(self, *, monthly_budget: float | None = None) -> None:
        self.monthly_budget = monthly_budget
        self.spend = 0.0
        self.history: list[dict[str, Any]] = []

    def score(self, model: ModelCandidate, workload: Workload,
              *, prefer_local: bool = False) -> float:
        weights = self._CAP_WEIGHTS
        value = (
            weights[Workload.QUALITY] * model.quality
            + weights[Workload.LATENCY] * (1.0 - min(1.0, model.latency_ms / 10000.0))
            + weights[Workload.COST] * (1.0 - min(1.0, model.cost_per_1k / 0.1))
            + weights[Workload.CONTEXT] * min(1.0, model.context_window / 200000.0)
            + weights[Workload.PRIVACY] * (1.0 if model.local else 0.0)
            + weights[Workload.LOCAL_RESOURCES] * (1.0 if model.local else 0.0)
        )
        if prefer_local and model.local:
            value += 0.15
        if workload is Workload.PRIVACY and not model.local:
            value -= 0.5
        return round(value, 6)

    def route(self, workload: Workload | str, candidates: list[ModelCandidate],
              *, prefer_local: bool = False, max_cost_per_1k: float | None = None
              ) -> RoutingDecision:
        task = workload if isinstance(workload, Workload) else Workload(str(workload))
        eligible = [m for m in candidates if m.available and m.supports(task)]
        if max_cost_per_1k is not None:
            eligible = [m for m in eligible if m.cost_per_1k <= max_cost_per_1k]
        if self.monthly_budget is not None and self.spend >= self.monthly_budget:
            eligible = [m for m in eligible if m.cost_per_1k == 0.0]
        if not eligible:
            return RoutingDecision(None, [], "no_available_model", self._now())
        ranked = sorted(eligible, key=lambda m: (-self.score(m, task, prefer_local=prefer_local), m.name))
        decision = RoutingDecision(ranked[0], ranked[1:], "scored", self._now())
        self.history.append({"at": decision.at, "workload": task.value,
                             "selected": ranked[0].name, "fallbacks": [m.name for m in ranked[1:]]})
        return decision

    def record_usage(self, model: ModelCandidate, tokens: int) -> float:
        cost = max(0, tokens) / 1000.0 * model.cost_per_1k
        self.spend += round(cost, 8)
        return round(cost, 8)

    def budget_remaining(self) -> float | None:
        return None if self.monthly_budget is None else round(self.monthly_budget - self.spend, 8)

    @staticmethod
    def _now() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
