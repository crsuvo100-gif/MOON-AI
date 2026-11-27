"""Capability catalogue and non-destructive registration for the V13 pack."""

from __future__ import annotations

import time
from typing import Any, Callable

from .cost_aware_routing import CostAwareRouter, ModelCandidate, Workload
from .deployment import DeploymentManager
from .feature_flags import FeatureFlagStore
from .memory_governance import GovernanceStore, Sensitivity
from .observability import Trace, redact
from .sbom import build_sbom
from .security_scorecard import SecurityScorecard

CAPABILITIES: tuple[str, ...] = (
    "v13.feature_flags", "v13.memory_governance", "v13.semantic_retrieval",
    "v13.cost_aware_routing", "v13.observability", "v13.security_scorecard",
    "v13.sbom", "v13.deployment_assessment",
)


def _check_flags(tmp: Any) -> None:
    store = FeatureFlagStore(tmp / "flags.json")
    store.register(__import__("app.v13.feature_flags", fromlist=["FeatureFlag"]).FeatureFlag(
        name="probe", description="self-check"))
    store.enable("probe")
    assert store.is_enabled("probe")
    store.disable("probe")
    assert not store.is_enabled("probe")


def _check_memory(tmp: Any) -> None:
    store = GovernanceStore(tmp / "memory.json")
    rec = store.add("MOON relies on governed memory with provenance.", source="self_check",
                    confidence=0.8, sensitivity=Sensitivity.PUBLIC, tags=("memory", "provenance"))
    assert store.get(rec.record_id) is not None
    store.verify(rec.record_id)
    from .semantic_memory import SemanticMemoryRetriever
    hits = SemanticMemoryRetriever(store).retrieve("governed memory provenance")
    assert hits and hits[0].record_id == rec.record_id


def _check_routing(tmp: Any) -> None:
    router = CostAwareRouter(monthly_budget=10.0)
    local = ModelCandidate("local", "ollama", frozenset({"reasoning", "coding"}),
                           local=True, quality=0.6, latency_ms=700)
    cloud = ModelCandidate("cloud", "example", frozenset({"reasoning", "coding"}),
                           cost_per_1k=0.01, quality=0.9, latency_ms=300)
    decision = router.route(Workload.REASONING, [local, cloud], prefer_local=True)
    assert decision.selected is not None and len(decision.fallbacks) == 1
    assert router.record_usage(cloud, 1000) > 0


def _check_observability(tmp: Any) -> None:
    trace = Trace(tmp / "trace.jsonl")
    with trace.span("tool", "probe", data={"api_key": "MUST_NOT_APPEAR"}):
        pass
    assert trace.summary()["events"] == 1
    assert "MUST_NOT_APPEAR" not in (tmp / "trace.jsonl").read_text(encoding="utf-8")
    assert redact({"token": "abc", "nested": {"password": "xyz"}}) == {
        "token": "[REDACTED]", "nested": {"password": "[REDACTED]"}
    }


def _check_scorecard(tmp: Any) -> None:
    result = SecurityScorecard().run()
    assert 0.0 <= result.score <= 100.0 and len(result.checks) == 5


def _check_sbom(tmp: Any) -> None:
    bom = build_sbom(write=False)
    assert bom["component_count"] > 0 and bom["components"]


def _check_deployment(tmp: Any) -> None:
    report = DeploymentManager().report()
    assert report["checks"] and "verified" in report


_CHECKS: tuple[tuple[str, Callable[[Any], None]], ...] = (
    ("v13.feature_flags", _check_flags),
    ("v13.memory_governance", _check_memory),
    ("v13.semantic_retrieval", _check_memory),
    ("v13.cost_aware_routing", _check_routing),
    ("v13.observability", _check_observability),
    ("v13.security_scorecard", _check_scorecard),
    ("v13.sbom", _check_sbom),
    ("v13.deployment_assessment", _check_deployment),
)


def self_check(tmp_path: Any) -> dict[str, Any]:
    """Run functional probes in a scratch directory; return structured results."""
    import tempfile
    from pathlib import Path
    results = {}
    # Each invocation gets its own scratch root. Some probes append to files
    # (e.g. trace.jsonl), so reusing a caller-supplied tmp_path across two
    # self_check calls must not make the second call fail on accumulated state.
    run_root = None
    if tmp_path is not None:
        run_root = Path(tempfile.mkdtemp(prefix="selfcheck-", dir=str(tmp_path)))
    for name, fn in _CHECKS:
        try:
            if run_root is None:
                with tempfile.TemporaryDirectory() as d:
                    fn(Path(d))
            else:
                fn(run_root / name.replace(".", "_"))
            results[name] = {"status": "pass", "detail": "functional self-check executed"}
        except Exception as exc:  # noqa: BLE001 - report, never hide
            results[name] = {"status": "fail", "detail": f"{type(exc).__name__}: {exc}"}
    return {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "results": results,
            "passed": sum(r["status"] == "pass" for r in results.values()),
            "failed": sum(r["status"] == "fail" for r in results.values())}


def register_capabilities(tmp_path: Any = None) -> dict[str, Any]:
    """Register only after self-check; writes to the ignored capabilities/ dir."""
    from app.capability.registry import CapabilityRecord, CapabilityRegistry
    check = self_check(tmp_path)
    registry = CapabilityRegistry()
    for name, result in check["results"].items():
        registry.upsert(CapabilityRecord(
            name=name, version="1.0.0",
            status="verified" if result["status"] == "pass" else "failed",
            source="local-module", runtime="python",
            health="healthy" if result["status"] == "pass" else "unhealthy",
            permissions=(), network_required=False, sandbox_required=False,
            dependencies=(), verified_at=check["checked_at"],
            notes="MOON V13 additive extension pack; " + result["detail"],
        ))
    return check
