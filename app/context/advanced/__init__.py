"""Advanced context self-function system for MOON-AI.

Every agent, brain, and tool can use this package to manage its own
context like a professional AI assistant:

- ContextWindow: token-budgeted context with automatic eviction
- ContextAwareness: self-monitoring and health assessment
- ContextInjector: prompt injection with multiple formats
- ContextLifecycle: lifecycle state machine for context items
- ContextRetriever: intelligent retrieval with semantic search
- ContextCompressor: compression when context is full
- ContextAnalytics: usage analytics and health scoring
- ContextOrchestrator: unified orchestrator tying it all together
"""

from app.context.advanced.context_analytics import ContextAnalytics, ContextAnalyticsTracker
from app.context.advanced.context_awareness import (
    ContextAwareness,
    ContextAwarenessState,
    ContextHealth,
)
from app.context.advanced.context_compressor import (
    CompressionResult,
    CompressionStrategy,
    ContextCompressor,
)
from app.context.advanced.context_injector import ContextInjector, InjectionFormat, InjectionResult
from app.context.advanced.context_lifecycle import ContextLifecycle, ContextPhase, LifecycleEvent
from app.context.advanced.context_orchestrator import ContextOrchestrator, ContextSnapshot
from app.context.advanced.context_retriever import ContextRetriever, RetrievalResult
from app.context.advanced.context_window import ContextItem, ContextWindow, EvictionPolicy

__all__ = [
    "CompressionResult",
    "CompressionStrategy",
    "ContextAnalytics",
    "ContextAnalyticsTracker",
    "ContextAwareness",
    "ContextAwarenessState",
    "ContextCompressor",
    "ContextHealth",
    "ContextInjector",
    "ContextItem",
    "ContextLifecycle",
    "ContextOrchestrator",
    "ContextPhase",
    "ContextRetriever",
    "ContextSnapshot",
    "ContextWindow",
    "EvictionPolicy",
    "InjectionFormat",
    "InjectionResult",
    "LifecycleEvent",
    "RetrievalResult",
]
