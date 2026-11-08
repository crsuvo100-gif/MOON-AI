"""Path and resource limits shared by local document and image tools."""

from __future__ import annotations

from pathlib import Path

MAX_MEDIA_FILE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 5_000_000


def resolve_media_input(path: str, allowed_root: str | Path = ".") -> Path:
    if not path:
        raise ValueError("file path is required")
    root = Path(allowed_root).resolve()
    candidate = (root / path).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("path escapes allowed root")
    if not candidate.is_file():
        raise ValueError("path is not a regular file")
    if candidate.stat().st_size > MAX_MEDIA_FILE_BYTES:
        raise ValueError(f"file exceeds {MAX_MEDIA_FILE_BYTES} bytes")
    return candidate
