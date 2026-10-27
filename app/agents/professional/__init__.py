"""Professional Agent System — advanced agent capabilities.

Provides professional-grade agent features:
- Communication Bus: event-driven inter-agent communication
- Task Queue: priority-based task scheduling
- Quality Gate: multi-stage output validation
- Self-Healing: proactive fault detection and recovery
- Proactive Suggestions: anticipates user needs
- Multi-Model Consensus: critical decision validation
- Execution Analytics: real-time performance monitoring
- Adaptive Prompts: dynamic prompt engineering
- Session Continuity: cross-session context management
- Knowledge Graph: integrated knowledge representation
"""

from app.agents.professional.adaptive_prompts import (
    AdaptivePrompts,
    PromptConfig,
    PromptTemplate,
    TaskComplexity,
    UserExpertise,
)
from app.agents.professional.communication_bus import (
    AgentEvent,
    CommunicationBus,
    EventPriority,
    Subscription,
)
from app.agents.professional.execution_analytics import (
    AnalyticsSummary,
    ExecutionAnalytics,
    ExecutionRecord,
    MetricPoint,
    MetricType,
)
from app.agents.professional.knowledge_graph import (
    Entity,
    EntityType,
    Fact,
    KnowledgeGraph,
    Relationship,
    RelationType,
)
from app.agents.professional.multi_model_consensus import (
    ConfidenceLevel,
    ConsensusResult,
    ConsensusStrategy,
    ModelResponse,
    MultiModelConsensus,
)
from app.agents.professional.proactive_suggestions import (
    ProactiveSuggestions,
    Suggestion,
    SuggestionPriority,
    SuggestionType,
    UserPattern,
)
from app.agents.professional.professional_orchestrator import (
    ProfessionalAgentOrchestrator,
)
from app.agents.professional.quality_gate import (
    QualityCheck,
    QualityGate,
    QualityLevel,
    QualityReport,
    QualityStage,
)
from app.agents.professional.self_healing import (
    CircuitBreaker,
    FailureType,
    HealthCheck,
    HealthStatus,
    RecoveryAction,
    SelfHealing,
)
from app.agents.professional.session_continuity import (
    SessionContext,
    SessionContinuity,
    SessionHandoff,
    SessionStatus,
)
from app.agents.professional.task_queue import (
    QueuedTask,
    TaskPriority,
    TaskQueue,
    TaskStatus,
)

__all__ = [
    "AdaptivePrompts",
    "AgentEvent",
    "AnalyticsSummary",
    "CircuitBreaker",
    "CommunicationBus",
    "ConfidenceLevel",
    "ConsensusResult",
    "ConsensusStrategy",
    "Entity",
    "EntityType",
    "EventPriority",
    "ExecutionAnalytics",
    "ExecutionRecord",
    "Fact",
    "FailureType",
    "HealthCheck",
    "HealthStatus",
    "KnowledgeGraph",
    "MetricPoint",
    "MetricType",
    "ModelResponse",
    "MultiModelConsensus",
    "ProactiveSuggestions",
    "ProfessionalAgentOrchestrator",
    "PromptConfig",
    "PromptTemplate",
    "QualityCheck",
    "QualityGate",
    "QualityLevel",
    "QualityReport",
    "QualityStage",
    "QueuedTask",
    "RecoveryAction",
    "RelationType",
    "Relationship",
    "SelfHealing",
    "SessionContext",
    "SessionContinuity",
    "SessionHandoff",
    "SessionStatus",
    "Subscription",
    "Suggestion",
    "SuggestionPriority",
    "SuggestionType",
    "TaskComplexity",
    "TaskPriority",
    "TaskQueue",
    "TaskStatus",
    "UserExpertise",
    "UserPattern",
]
