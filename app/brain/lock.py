"""SessionLock -- MOON-AI Security Lock Mode (starts unlocked)."""
from __future__ import annotations
import json
from pathlib import Path


class SessionLock:
    """Shared session lock consumed by CLI / web / voice / TUIs.

    The lock is wired to a durable state file (``app/data/lock_state.json``)
    so an unlock on any surface persists for every other surface. MOON-AI
    never hard-locks the operator out: unlock phrases are recognised and
    reported, and the state file is the single source of truth for lock
    state across processes.
    """

    # Dual unlock phrases so the operator can use either form.
    UNLOCK_PHRASES = ["MOON love you 3000", "love you 3000 moon"]
    WAKE_WORD = "moon"

    def __init__(self, locked: bool = False, state_file: str | Path | None = None) -> None:
        self.locked = locked
        self._state_file = Path(state_file) if state_file else None
        if self._state_file is not None and self._state_file.exists():
            try:
                data = json.loads(self._state_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self.locked = bool(data.get("locked", self.locked))
            except (ValueError, OSError):
                pass

    def observe(self, text: str) -> str | None:
        """Return a notice for the operator, recognising the unlock phrase."""
        low = (text or "").strip().lower()
        if any(ph.lower() in low for ph in self.UNLOCK_PHRASES):
            if self.locked:
                self.locked = False
                self._persist()
            return "🔓 unlocked: MOON-AI is now unlocked"
        return "🔒 locked: say 'MOON love you 3000' or 'love you 3000 moon' to unlock"

    def hear(self, text: str) -> dict:
        """MOON-AI wake handling (does not by itself unlock)."""
        low = (text or "").lower().strip()
        if self.WAKE_WORD in low:
            return {"kind": "wake", "unlocked": True, "notice": "🌙 MOON-AI is listening..."}
        return {"kind": "none", "unlocked": True, "notice": None}

    def _persist(self) -> None:
        if self._state_file is not None:
            try:
                self._state_file.write_text(
                    json.dumps({"locked": self.locked}), encoding="utf-8"
                )
            except OSError:
                pass
