"""Cybersecurity Laboratory -- MOON's own approved-tool runtime.

MOON operates this subsystem through its own application lifecycle
(app.terminal_interface / app.brain.orchestrator / app.api.interface). It is
NOT a Hermes-dependent module: once the laboratory is installed, already-verified
capabilities are discovered, authorized, executed and audited purely by MOON's
own runtime objects.

Lifecycle states (DISCOVERED -> ... -> ENABLED) plus terminal states.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only (runtime import is lazy below)
    from app.laboratory.core import Laboratory

logger = logging.getLogger(__name__)

_LAB: "Laboratory | None" = None


def get_laboratory() -> "Laboratory":
    """Return the Laboratory singleton. Lazy-initialises on first use."""
    global _LAB
    if _LAB is None:
        # Imported lazily: Laboratory lives in app.laboratory.core and imports
        # this package, so a module-level import would be circular (and the
        # unimported name previously raised NameError on first use).
        from app.laboratory.core import Laboratory

        _LAB = Laboratory()
    return _LAB
