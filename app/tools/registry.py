"""Tool registry -- name -> tool instance."""

from __future__ import annotations

import logging

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool
        logger.debug("registered tool %s", tool.name)

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def all(self) -> list[BaseTool]:
        return list(self._tools.values())

    def all_tools(self) -> list[BaseTool]:
        """Alias used by capability reports / tooling consumers."""
        return self.all()

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools)

# Module-level singleton (lazy import-safe) -- mirrors app/agents/registry.py.
_REGISTRY: "ToolRegistry | None" = None


def get_registry() -> "ToolRegistry":
    """Return the canonical tool registry singleton (parallel to app/agents)."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = ToolRegistry()
    return _REGISTRY


__all__ = ["BaseTool", "ToolRegistry", "get_registry"]
