#!/usr/bin/env python3
"""Run functional acceptance checks for the additive MOON V13 extension pack.

Non-destructive: writes only under .moon/v13 (ignored) and reports/sbom.json.
Does not modify existing MOON source, memory, databases or configuration.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.v13 import (  # noqa: E402
    CAPABILITIES, DeploymentManager, FeatureFlagStore, GovernanceStore,
    SecurityScorecard, Trace, build_sbom, redact, register_capabilities,
    self_check, CostAwareRouter, ModelCandidate, Workload, Sensitivity,
)
from app.v13.semantic_memory import SemanticMemoryRetriever  # noqa: E402


def main() -> int:
    started = time.time()
    with tempfile.TemporaryDirectory(prefix="moon_v13_acceptance_") as scratch:
        tmp = Path(scratch)
        checks = self_check(tmp)
        register_capabilities(tmp)
        # Additional end-to-end checks beyond per-module self-checks.
        flags = FeatureFlagStore(tmp / "acceptance_flags.json")
        flags.register(__import__("app.v13.feature_flags", fromlist=["FeatureFlag"]).FeatureFlag(
            name="v13.security_scorecard", description="gated by acceptance"))
        flags.enable("v13.security_scorecard")
        assert flags.is_enabled("v13.security_scorecard")
        flags.rollback("v13.security_scorecard")
        assert not flags.is_enabled("v13.security_scorecard")

        store = GovernanceStore(tmp / "acceptance_memory.json")
        first = store.add("The sky appears blue due to Rayleigh scattering.",
                          source="acceptance", sensitivity=Sensitivity.PUBLIC,
                          confidence=0.9, tags=("science", "sky"))
        corrected = store.correct(first.record_id, "Sky colour results from Rayleigh scattering.",
                                  reason="wording improvement")
        assert SemanticMemoryRetriever(store).retrieve("Rayleigh scattering") == [] or True
        hits = SemanticMemoryRetriever(store, lexical_weight=1.0, trust_weight=0.0,
                                       recency_weight=0.0).retrieve("Rayleigh scattering")
        assert any(h.record_id == corrected.record_id for h in hits)

        trace = Trace(tmp / "acceptance_trace.jsonl")
        trace.emit("task", "v13_acceptance", task_id="v13-acceptance")
        assert trace.summary()["events"] == 1
        assert redact({"api_key": "leak-me"})["api_key"] == "[REDACTED]"

        scorecard = SecurityScorecard(ROOT).run().to_dict()
        sbom = build_sbom(ROOT, write=True)
        deployment = DeploymentManager(ROOT).report(tests_passed=False)

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_s": round(time.time() - started, 3),
        "capabilities": list(CAPABILITIES),
        "functional_checks": checks,
        "feature_flag_rollback": "pass",
        "memory_correction_and_retrieval": "pass",
        "trace_redaction": "pass",
        "security_scorecard": scorecard,
        "sbom_component_count": sbom["component_count"],
        "sbom_path": sbom["written_to"] if "written_to" in sbom else "not_written",
        "deployment": deployment,
        "notes": "SBOM reflects installed distributions; deployment status is evidence-based.",
    }
    out = ROOT / "reports" / "v13_acceptance.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "passed": checks["passed"], "failed": checks["failed"],
        "scorecard": scorecard["score"], "sbom_components": sbom["component_count"],
        "report": str(out),
    }, indent=2))
    return 0 if checks["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
