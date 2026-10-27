"""Advanced memory system -- unified search, consolidation, proactive surfacing,
reasoning, conflict resolution, importance scoring, temporal reasoning, lifecycle
management, summarization, clustering, recommendations, forgetting curves,
association engine, query planning, memory export, validation, and deduplication.

Professional AI assistants don't just store memories; they actively manage
them: search across ALL memory types simultaneously, consolidate important
findings across subsystems, proactively surface relevant context, maintain
cross-session continuity, reason over stored knowledge, resolve conflicts,
score importance, manage lifecycle, summarize, cluster, recommend, model
forgetting curves, build associations, plan complex queries, export memories,
validate quality, and deduplicate.

Additive only -- never replaces existing modules.
"""

from app.memory.advanced.association_engine import Association, AssociationEngine, AssociationPath
from app.memory.advanced.clustering import MemoryCluster, MemoryClustering
from app.memory.advanced.conflict_resolver import Conflict, ConflictResolver, Resolution
from app.memory.advanced.deduplication import (
    DeduplicationReport,
    DuplicateGroup,
    MemoryDeduplicator,
    MergeResult,
)
from app.memory.advanced.forgetting_curve import (
    ForgettingCurve,
    ForgettingCurveManager,
    ReviewSchedule,
)
from app.memory.advanced.importance_scorer import ImportanceScore, ImportanceScorer
from app.memory.advanced.lifecycle import LifecycleAction, LifecycleManager, LifecycleReport
from app.memory.advanced.memory_exporter import ExportResult, MemoryExporter
from app.memory.advanced.memory_validator import MemoryValidator, ValidationIssue, ValidationReport
from app.memory.advanced.query_planner import PlannedResult, QueryPlan, QueryPlanner, SubQuery
from app.memory.advanced.reasoning import MemoryReasoningEngine, ReasoningChain, ReasoningResult
from app.memory.advanced.recommendation import MemoryRecommendation, MemoryRecommender
from app.memory.advanced.summarization import MemorySummarizer, MemorySummary
from app.memory.advanced.temporal_reasoning import TemporalDiff, TemporalFact, TemporalReasoner

__all__ = [
    "Association",
    "AssociationEngine",
    "AssociationPath",
    "Conflict",
    "ConflictResolver",
    "DeduplicationReport",
    "DuplicateGroup",
    "ExportResult",
    "ForgettingCurve",
    "ForgettingCurveManager",
    "ImportanceScore",
    "ImportanceScorer",
    "LifecycleAction",
    "LifecycleManager",
    "LifecycleReport",
    "MemoryCluster",
    "MemoryClustering",
    "MemoryDeduplicator",
    "MemoryExporter",
    "MemoryReasoningEngine",
    "MemoryRecommendation",
    "MemoryRecommender",
    "MemorySummarizer",
    "MemorySummary",
    "MemoryValidator",
    "MergeResult",
    "PlannedResult",
    "QueryPlan",
    "QueryPlanner",
    "ReasoningChain",
    "ReasoningResult",
    "Resolution",
    "ReviewSchedule",
    "SubQuery",
    "TemporalDiff",
    "TemporalFact",
    "TemporalReasoner",
    "ValidationIssue",
    "ValidationReport",
]
