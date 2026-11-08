"""PDF reader tool (optional; requires pypdf)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.tools.base import BaseTool
from app.tools.local_media import resolve_media_input

logger = logging.getLogger(__name__)


class PdfReaderTool(BaseTool):
    name = "pdf_reader"
    description = "Extract text from a PDF file."

    def __init__(self, enabled: bool = False, allowed_root: str = ".") -> None:
        self._enabled = enabled
        self._root = Path(allowed_root).resolve()

    async def execute(self, path: str = "", **kwargs: Any) -> str:
        if not self._enabled:
            return "[pdf disabled]"
        try:
            source = resolve_media_input(path, self._root)
            from pypdf import PdfReader

            parts: list[str] = []
            remaining = 4_000
            with source.open("rb") as handle:
                reader = PdfReader(handle)
                for page in reader.pages[:10]:
                    text = page.extract_text() or ""
                    parts.append(text[:remaining])
                    remaining -= len(parts[-1])
                    if remaining <= 0:
                        parts.append("[text truncated]")
                        break
            return "\n".join(parts)
        except Exception as exc:  # noqa: BLE001
            return f"[pdf error: {exc}]"
