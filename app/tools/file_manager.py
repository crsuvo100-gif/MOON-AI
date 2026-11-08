"""File manager tool (read/write/list within an allowed root)."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)

_MAX_READ_CHARS = 4_000
_MAX_WRITE_BYTES = 1_000_000
_MAX_LIST_ENTRIES = 200


class FileManagerTool(BaseTool):
    name = "file_manager"
    description = "Read, write, or list files within the allowed root."

    def __init__(self, allowed_root: str = ".") -> None:
        self._root = Path(allowed_root).resolve()

    def _safe(self, path: str) -> Path:
        p = (self._root / path).resolve()
        if self._root not in p.parents and p != self._root:
            raise ValueError("path escapes allowed root")
        return p

    def is_dangerous(self) -> bool:
        return True

    async def execute(self, action: str = "read", path: str = "", content: str = "", **kwargs: Any) -> str:
        try:
            p = self._safe(path)
            if action == "read":
                with p.open(encoding="utf-8", errors="replace") as handle:
                    return handle.read(_MAX_READ_CHARS)
            if action == "write":
                text = content or ""
                if len(text.encode("utf-8")) > _MAX_WRITE_BYTES:
                    return f"[file_manager error: content exceeds {_MAX_WRITE_BYTES} bytes]"
                p.parent.mkdir(parents=True, exist_ok=True)
                p = self._safe(path)
                temporary: Path | None = None
                try:
                    with tempfile.NamedTemporaryFile(
                        mode="w",
                        encoding="utf-8",
                        dir=p.parent,
                        prefix=f".{p.name}.",
                        suffix=".tmp",
                        delete=False,
                    ) as handle:
                        temporary = Path(handle.name)
                        handle.write(text)
                        handle.flush()
                        os.fsync(handle.fileno())
                    if kwargs.get("overwrite") is True:
                        os.replace(temporary, p)
                    else:
                        os.link(temporary, p)
                finally:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
                return f"wrote {path}"
            if action == "list":
                with os.scandir(p) as entries:
                    names = []
                    for entry in entries:
                        names.append(entry.name)
                        if len(names) > _MAX_LIST_ENTRIES:
                            break
                truncated = len(names) > _MAX_LIST_ENTRIES
                output = names[:_MAX_LIST_ENTRIES]
                if truncated:
                    output.append("[list truncated]")
                return "\n".join(output)
            return "[unknown action]"
        except Exception as exc:  # noqa: BLE001
            return f"[file_manager error: {exc}]"
