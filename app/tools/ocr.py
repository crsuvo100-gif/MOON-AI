"""OCR tool (optional; requires pytesseract + tesseract)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.tools.base import BaseTool
from app.tools.local_media import MAX_IMAGE_PIXELS, resolve_media_input

logger = logging.getLogger(__name__)


class OcrTool(BaseTool):
    name = "ocr"
    description = "Extract text from an image via OCR."

    def __init__(self, enabled: bool = False, allowed_root: str = ".") -> None:
        self._enabled = enabled
        self._root = Path(allowed_root).resolve()

    async def execute(self, path: str = "", **kwargs: Any) -> str:
        if not self._enabled:
            return "[ocr disabled]"
        try:
            source = resolve_media_input(path, self._root)
            import pytesseract
            from PIL import Image

            with Image.open(source) as image:
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    return f"[ocr error: image exceeds {MAX_IMAGE_PIXELS} pixels]"
                return pytesseract.image_to_string(image, timeout=5)[:2000]
        except Exception as exc:  # noqa: BLE001
            return f"[ocr error: {exc}]"
