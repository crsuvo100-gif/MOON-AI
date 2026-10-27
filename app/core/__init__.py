"""MOON-AI Core package (spec section 6: core/).

Compatibility layer surfacing the real brain/config/runtime at the spec path.
The Master Orchestrator brain lives at app.brain; config at app.config; runtime
spine at app.runtime. Non-destructive.
"""

from __future__ import annotations

from app.brain.orchestrator import Orchestrator
from app.config import settings

try:
    from app.runtime import integration  # type: ignore
except Exception:  # noqa: BLE001
    integration = None

__all__ = ["Orchestrator", "integration", "settings"]
