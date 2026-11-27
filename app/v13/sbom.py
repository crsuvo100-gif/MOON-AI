"""Software bill of materials built from real installed distribution metadata."""

from __future__ import annotations

import hashlib
import importlib.metadata
import platform
import time
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return ""


def build_sbom(root: str | Path | None = None, *, write: bool = False) -> dict[str, Any]:
    """Generate an SBOM; ``write=True`` stores it under reports/sbom.json."""
    repo = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    components = []
    for dist in sorted(importlib.metadata.distributions(), key=lambda d: (d.metadata["Name"] or "").lower()):
        name = dist.metadata["Name"] or "unknown"
        components.append({
            "name": name,
            "version": dist.version,
            "license": ((dist.metadata.get("License") or "").splitlines() or ["unknown"])[0][:120] or "unknown",
            "source": "installed-distribution",
        })
    lock = repo / "requirements.txt"
    sbom = {
        "bomFormat": "custom-moon-sbom",
        "version": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "project": {"name": "moon-ai-agent", "root": str(repo)},
        "requirements_sha256": _sha256(lock) if lock.exists() else "",
        "components": components,
        "component_count": len(components),
        "note": "Installed-distribution metadata; hashes and licences are reported as-found, not reviewed.",
    }
    if write:
        out = repo / "reports" / "sbom.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(__import__("json").dumps(sbom, indent=2), encoding="utf-8")
        sbom["written_to"] = str(out)
    return sbom
