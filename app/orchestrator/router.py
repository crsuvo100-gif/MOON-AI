"""Agent Router (spec sections 12, 6: orchestrator/router.py).

Re-exports the real AgentRouter from app.runtime.agent_router (non-destructive
compatibility layer for the spec directory layout).
"""

from app.agents.registry import get_registry
from app.runtime.agent_router import AgentRouter

__all__ = ["AgentRouter", "get_registry"]
