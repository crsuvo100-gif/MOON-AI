"""System command tool -- controlled host command execution (additive).

Replaces the earlier hard-coded shell passthrough with the same safe guard
rails as TerminalTool, so it can be wired into both the agent tool registry
and the orchestrator's inline list without duplicating logic.
"""

from __future__ import annotations

import logging
from typing import Any

from app.tools.base import BaseTool
from app.tools.process_capture import run_bounded_process

logger = logging.getLogger(__name__)

_REFUSE = ("rm -rf", "shutdown", "reboot", "dd if=")


class SystemCommandTool(BaseTool):
    name = "system_command"
    description = "Run a controlled system command (guarded)."

    def is_dangerous(self) -> bool:
        return True

    async def execute(self, command: str = "", **kwargs: Any) -> str:
        if not command:
            return "[no command]"
        if len(command) > 10_000:
            return "[system_command error: command exceeds 10000 characters]"
        low = command.lower()
        if any(d in low for d in _REFUSE):
            return "[refused: potentially dangerous command]"
        try:
            result = await run_bounded_process(
                command,
                shell=True,
                timeout=30,
                stdout_limit=2_000,
                stderr_limit=500,
            )
            output = result.stdout + result.stderr
            if result.timed_out:
                return "[system_command error: execution timed out]\n" + output
            return output
        except Exception as exc:  # noqa: BLE001
            return f"[system_command error: {exc}]"
