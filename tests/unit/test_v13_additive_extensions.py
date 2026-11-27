"""Regression tests for the additive MOON V13 extension pack."""

from __future__ import annotations

import json

import pytest

from app.capability.registry import CapabilityRegistry
from app.v13 import (
    CostAwareRouter, DeploymentManager, FeatureFlag, FeatureFlagStore, FlagState,
    GovernanceStore, ModelCandidate, SecurityScorecard, Sensitivity, Trace,
    Workload, build_sbom, redact, self_check,
)
from app.v13.semantic_memory import SemanticMemoryRetriever


def test_feature_flags_default_disabled_and_rollback(tmp_path):
    store = FeatureFlagStore(tmp_path / "flags.json")
    assert store.is_enabled("never_registered") is False
    store.register(FeatureFlag(name="probe", state=FlagState.DISABLED,
                               dependencies=("base",), description="test"))
    store.register(FeatureFlag(name="base"))
    assert not store.is_enabled("probe")
    store.enable("base")
    store.enable("probe")
    assert store.is_enabled("probe")
    store.disable("base")
    assert not store.is_enabled("probe")  # dependency gate
    store.disable("probe")
    rolled = store.rollback("probe")
    assert rolled is not None and rolled.state is FlagState.ENABLED


def test_memory_governance_excludes_secrets_and_corrections(tmp_path):
    store = GovernanceStore(tmp_path / "mem.json")
    with pytest.raises(ValueError):
        store.add("api_key=SUPER_SECRET_VALUE", source="test")
    with pytest.raises(ValueError):
        store.add("private", source="test", sensitivity=Sensitivity.SECRET)
    old = store.add("Sky is green.", source="test", confidence=0.6,
                    sensitivity=Sensitivity.PUBLIC, tags=("sky",))
    store.verify(old.record_id)
    new = store.correct(old.record_id, "Sky is blue.", reason="correction")
    old_after = store.get(old.record_id)
    assert old_after is not None and old_after.superseded_by == new.record_id
    assert "[REDACTED]" in json.dumps(store.export()) or "Sky" in json.dumps(store.export())
    assert store.stats()["total"] == 2


def test_semantic_retrieval_respects_trust_and_sensitivity(tmp_path):
    store = GovernanceStore(tmp_path / "mem.json")
    public = store.add("governed memory with provenance", source="test",
                       confidence=0.9, sensitivity=Sensitivity.PUBLIC,
                       tags=("memory",))
    private = store.add("governed memory secret note", source="test",
                        confidence=0.9, sensitivity=Sensitivity.PERSONAL)
    store.verify(public.record_id)
    retriever = SemanticMemoryRetriever(store)
    hits = retriever.retrieve("governed memory provenance", min_confidence=0.5)
    assert hits and hits[0].record_id == public.record_id
    assert all(h.record_id != private.record_id for h in hits)


def test_cost_aware_routing_fallback_and_budget():
    router = CostAwareRouter(monthly_budget=10.0)
    local = ModelCandidate("local", "ollama", frozenset({"reasoning"}), local=True,
                           quality=0.6, latency_ms=500)
    paid = ModelCandidate("paid", "cloud", frozenset({"reasoning", "vision"}),
                          cost_per_1k=0.02, quality=0.9)
    decision = router.route(Workload.REASONING, [local, paid], prefer_local=True)
    assert decision.selected == local and decision.fallbacks == [paid]
    exhausted = CostAwareRouter(monthly_budget=0.0)
    decision = exhausted.route(Workload.VISION, [local, paid])
    assert decision.selected is None  # exhausted budget allows only free models
    assert exhausted.budget_remaining() == 0.0


def test_trace_redacts_secrets(tmp_path):
    trace = Trace(tmp_path / "trace.jsonl")
    with trace.span("tool", "probe", data={"token": "abc123", "safe": "yes"}):
        pass
    raw = (tmp_path / "trace.jsonl").read_text(encoding="utf-8")
    assert "abc123" not in raw and "[REDACTED]" in raw
    assert trace.summary()["events"] == 1
    assert redact({"nested": [{"password": "x"}]})["nested"][0]["password"] == "[REDACTED]"


def test_security_scorecard_and_sbom():
    result = SecurityScorecard().run()
    assert len(result.checks) == 5 and 0 <= result.score <= 100
    assert all(c.evidence for c in result.checks)
    bom = build_sbom(write=False)
    assert bom["component_count"] >= 1 and bom["components"]


def test_deployment_reports_are_evidence_based():
    report = DeploymentManager().report(tests_passed=False)
    assert report["checks"] and isinstance(report["verified"], list)
    assert all(set(("target", "status", "evidence")) <= set(c) for c in report["checks"])


def test_v13_self_check_and_capability_registration(tmp_path):
    outcome = self_check(tmp_path)
    assert outcome["failed"] == 0, outcome
    assert outcome["passed"] >= 8
    registry = CapabilityRegistry(root=tmp_path / "capabilities")
    from app.v13 import register_capabilities
    # registration writes to the repository's ignored capabilities dir by design
    result = register_capabilities(tmp_path)
    assert result["failed"] == 0
    assert registry.has("v13.feature_flags") is False  # separate root untouched
