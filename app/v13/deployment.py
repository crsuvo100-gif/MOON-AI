"""Honest deployment-target assessment; no target is 'deployed' without evidence."""

from __future__ import annotations

import os
import platform
import shutil
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class Target(str, Enum):
    LOCAL = "local"
    VM_LINUX = "vm_linux"
    CONTAINER = "container"
    CLOUD_VPS = "cloud_vps"
    WINDOWS = "windows"
    MACOS = "macos"


class Status(str, Enum):
    VERIFIED = "verified"
    FAILED = "failed"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    NOT_AVAILABLE = "not_available"


@dataclass(frozen=True)
class DeploymentCheck:
    target: Target
    status: Status
    evidence: str

    def to_dict(self) -> dict[str, str]:
        return {"target": self.target.value, "status": self.status.value,
                "evidence": self.evidence}


class DeploymentManager:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else Path(__file__).resolve().parents[2]

    def probe_local(self, *, tests_passed: bool = False) -> DeploymentCheck:
        venv = (self.root / ".venv" / "bin" / "python").exists()
        viable = venv and sys.version_info >= (3, 10)
        if not viable:
            return DeploymentCheck(Target.LOCAL, Status.FAILED,
                                   f"python={platform.python_version()} venv={venv}")
        if tests_passed:
            return DeploymentCheck(Target.LOCAL, Status.VERIFIED,
                                   f"python={platform.python_version()} venv={venv} tests=passed")
        return DeploymentCheck(Target.LOCAL, Status.PARTIAL,
                               f"python={platform.python_version()} venv={venv} tests=not_run")

    def probe_container(self) -> DeploymentCheck:
        if not shutil.which("docker") and not (self.root / "Dockerfile").exists():
            return DeploymentCheck(Target.CONTAINER, Status.NOT_AVAILABLE,
                                   "no docker binary and no Dockerfile")
        return DeploymentCheck(Target.CONTAINER, Status.PARTIAL,
                               "container tooling present; image build not executed")

    def probe_platform(self) -> list[DeploymentCheck]:
        system = platform.system()
        checks = []
        if system == "Linux":
            checks.append(DeploymentCheck(Target.VM_LINUX, Status.VERIFIED,
                                          f"running on Linux: {platform.release()}"))
        elif system == "Windows":
            checks.append(DeploymentCheck(Target.WINDOWS, Status.VERIFIED,
                                          f"running on Windows: {platform.release()}"))
        else:
            checks.append(DeploymentCheck(Target.WINDOWS, Status.NOT_AVAILABLE,
                                          f"host platform={system}"))
        if system != "Darwin":
            checks.append(DeploymentCheck(Target.MACOS, Status.NOT_AVAILABLE,
                                          f"host platform={system}"))
        else:
            checks.append(DeploymentCheck(Target.MACOS, Status.VERIFIED,
                                          f"running on macOS: {platform.release()}"))
        checks.append(DeploymentCheck(Target.CLOUD_VPS, Status.BLOCKED,
                                      "no cloud credentials or deployment target configured"))
        return checks

    def report(self, *, tests_passed: bool = False) -> dict[str, Any]:
        checks = [self.probe_local(tests_passed=tests_passed), self.probe_container()]
        checks.extend(self.probe_platform())
        return {"checked_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime()),
                "checks": [c.to_dict() for c in checks],
                "verified": [c.target.value for c in checks if c.status is Status.VERIFIED],
                "note": "Target availability is evidence-based; no remote deployment is claimed."}
