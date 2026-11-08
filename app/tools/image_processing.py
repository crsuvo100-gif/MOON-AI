"""Image processing tool (optional; requires Pillow)."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from app.tools.base import BaseTool
from app.tools.local_media import MAX_IMAGE_PIXELS, MAX_MEDIA_FILE_BYTES, resolve_media_input

logger = logging.getLogger(__name__)


class ImageProcessingTool(BaseTool):
    name = "image_processing"
    description = "Basic image transforms (resize/convert) via Pillow."

    def __init__(self, enabled: bool = False, allowed_root: str = ".") -> None:
        self._enabled = enabled
        self._root = Path(allowed_root).resolve()

    async def execute(self, path: str = "", action: str = "info", **kwargs: Any) -> str:
        if not self._enabled:
            return "[image processing disabled]"
        try:
            source = resolve_media_input(path, self._root)
            from PIL import Image

            with Image.open(source) as image:
                width, height = image.size
                if width < 1 or height < 1:
                    return "[image error: image dimensions are invalid]"
                if width * height > MAX_IMAGE_PIXELS:
                    return f"[image error: image exceeds {MAX_IMAGE_PIXELS} pixels]"
                if action == "info":
                    return f"size={image.size} mode={image.mode}"
                if action != "resize":
                    return "[unknown action]"

                target_width = int(kwargs.get("width", 256))
                target_height = int(target_width * height / width)
                if (
                    not 1 <= target_width <= 4096
                    or not 1 <= target_height <= 4096
                    or target_width * target_height > MAX_IMAGE_PIXELS
                ):
                    return "[image error: requested dimensions exceed limits]"

                image.load()
                resized = image.resize((target_width, target_height))
                output = Path(f"{source}.resized.png")
                temporary: Path | None = None
                try:
                    with tempfile.NamedTemporaryFile(
                        dir=output.parent,
                        prefix=f".{output.name}.",
                        suffix=".tmp",
                        delete=False,
                    ) as handle:
                        temporary = Path(handle.name)
                        resized.save(handle, format="PNG")
                        handle.flush()
                        os.fsync(handle.fileno())
                    if temporary.stat().st_size > MAX_MEDIA_FILE_BYTES:
                        return f"[image error: output exceeds {MAX_MEDIA_FILE_BYTES} bytes]"
                    os.link(temporary, output)
                finally:
                    resized.close()
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
                return str(output)
        except Exception as exc:  # noqa: BLE001
            return f"[image error: {exc}]"
