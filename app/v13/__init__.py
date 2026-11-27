"""Additive MOON V13 extension pack.

Every module here is opt-in and standard-library-only. Importing this package
never activates a feature: flags default to DISABLED and no existing MOON code
path is patched. See reports/MOON_V13_IMPLEMENTATION_REPORT.md for evidence.
"""

from .feature_flags import FeatureFlagStore, FeatureFlag, FlagState
from .memory_governance import GovernanceStore, GovernanceRecord, Sensitivity
from .semantic_memory import SemanticMemoryRetriever, MemoryHit
from .cost_aware_routing import CostAwareRouter, ModelCandidate, Workload
from .observability import Trace, EventKind, redact
from .security_scorecard import SecurityScorecard, Verdict
from .sbom import build_sbom
from .deployment import DeploymentManager, Target, Status
from .catalog import self_check, register_capabilities, CAPABILITIES

__all__ = [
    "FeatureFlagStore", "FeatureFlag", "FlagState",
    "GovernanceStore", "GovernanceRecord", "Sensitivity",
    "SemanticMemoryRetriever", "MemoryHit",
    "CostAwareRouter", "ModelCandidate", "Workload",
    "Trace", "EventKind", "redact",
    "SecurityScorecard", "Verdict",
    "build_sbom", "DeploymentManager", "Target", "Status",
    "self_check", "register_capabilities", "CAPABILITIES",
]
