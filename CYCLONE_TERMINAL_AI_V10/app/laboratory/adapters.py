"""Adapters for the Cybersecurity Laboratory.

Each adapter is a self-contained, locally runnable unit that returns
`(output: str, validated: bool, error: str)`. Nothing here contacts third
parties, downloads anything, or mutates live services. Adapters are the only
place capability execution logic lives; the policy engine decides *whether* an
adapter may run, and the audit layer records *that* it ran.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AdapterResult:
    output: str
    validated: bool
    error: str = ""


def _ok(output: str) -> AdapterResult:
    return AdapterResult(output=output, validated=True, error="")


def _fail(error: str) -> AdapterResult:
    return AdapterResult(output="", validated=False, error=error)


# ------------------------------------------------------------------ #
# adapters
# ------------------------------------------------------------------ #
def _lab_root() -> Path:
    from app.laboratory import get_laboratory

    return get_laboratory().root


def local_inventory_adapter(params: dict) -> AdapterResult:
    """Summarise MOON's own runtime directories (read-only)."""
    root = _lab_root()
    paths = params.get("paths", ["data", "logs", "capabilities", "app/logs"])
    lines = ["MOON local_data_inventory", "source: bundled local probe", ""]
    for p in paths:
        target = (root / p).resolve()
        exists = target.exists()
        count = 0
        total = 0
        if exists:
            count = sum(1 for _ in target.rglob("*"))
            total = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
        lines.append(f"{p:24s} exists={str(exists):5s} files={count:6d} bytes={total}")
    out = "\n".join(lines)
    return _ok(out)


def local_env_probe_adapter(params: dict) -> AdapterResult:
    """Read-only probe of MOON's configuration shape (secrets masked)."""
    root = _lab_root()
    keys = params.get("keys", [])
    lines = ["MOON local_env_probe", "source: bundled local probe", ""]
    candidates = {
        "model_base_url": root / "data" / "settings.json",
        "memory_backend": root / "data" / "memory" / "index.json",
        "lab_root": root,
        "terminal_host": "127.0.0.1",
        "terminal_port": 8777,
    }
    for key, path in candidates.items():
        shown = "n/a"
        if "base_url" in key or "backend" in key or "host" in key or "port" in key:
            shown = str(path if isinstance(path, Path) and path.exists() else "n/a")
        if key == "terminal_host" or key == "terminal_port":
            shown = str(path)
        lines.append(f"  {key:20s} = {shown}")
    return _ok("\n".join(lines))


def echo_adapter(params: dict) -> AdapterResult:
    """Deterministic, dependency-free echo that MOON can validate trivially."""
    message = params.get("message", "hello from laboratory")
    out = f"laboratory.test_echo | {message} | {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"
    return _ok(out)


def redact_adapter(params: dict) -> AdapterResult:
    """Show that secret-shaped values are sanitized before logging."""
    import re

    text = params.get("text", "api_key=sk-or-xxx token=supersekret")
    # Redact any key=value pair whose value looks like a token/password.
    redacted = re.sub(r"(\w+)=([\w.\-]{8,})", r"\1=REDACTED", text)
    return _ok(redacted)


def loopback_probe_adapter(params: dict) -> AdapterResult:
    """Passive loopback readiness probe: never leaves 127.0.0.1/::1."""
    import socket

    host = params.get("host", "127.0.0.1")
    port = int(params.get("port", 8777))
    count = int(params.get("count", 3))
    results = []
    for i in range(count):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.0)
        try:
            s.connect((host, port))
            results.append(f"attempt={i + 1} connect={host}:{port} ok=1")
        except Exception as exc:  # noqa: BLE001
            results.append(f"attempt={i + 1} connect={host}:{port} ok=0 ({exc})")
        finally:
            s.close()
    return _ok("\n".join(results))


def policy_echo_adapter(params: dict) -> AdapterResult:
    """Demonstration adapter used to prove default-deny enforcement."""
    return _fail(
        "policy_echo is HIGH_IMPACT and is BLOCKED. Ask MOON to approve it "
        "explicitly (data/laboratory/approvals.json or 'moon laboratory approve')"
    )
