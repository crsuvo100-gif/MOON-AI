"""Python executor tool (sandboxed subprocess, time-limited)."""

from __future__ import annotations

import logging
import sys
from typing import Any

from app.tools.base import BaseTool
from app.tools.process_capture import run_bounded_process

logger = logging.getLogger(__name__)

_MAX_CODE_CHARS = 100_000


class PythonExecutorTool(BaseTool):
    name = "python_executor"
    description = "Run a bounded Python snippet and return stdout."

    def is_dangerous(self) -> bool:
        return True

    async def execute(self, code: str = "", **kwargs: Any) -> str:
        if not code:
            return "[no code]"
        if len(code) > _MAX_CODE_CHARS:
            return f"[python error: code exceeds {_MAX_CODE_CHARS} characters]"
        try:
            result = await run_bounded_process(
                [sys.executable, "-c", code],
                timeout=30,
                stdout_limit=2_000,
                stderr_limit=500,
            )
            if result.timed_out:
                return "[python error: execution timed out]\n" + result.stdout + result.stderr
            return result.stdout + result.stderr
        except Exception as exc:  # noqa: BLE001
            return f"[python error: {exc}]"
