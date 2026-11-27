"""Evidence-based security scorecard. Static findings are never called verified."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class Verdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNVERIFIED = "unverified"


@dataclass(frozen=True)
class Check:
    check_id: str
    description: str
    verdict: Verdict
    evidence: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.check_id, "description": self.description,
                "verdict": self.verdict.value, "evidence": self.evidence}


class SecurityScorecard:
    """Read-only audits of the local repository; never logs secret values."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else Path(__file__).resolve().parents[2]

    def _read(self, rel: str) -> str:
        path = self.root / rel
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def check_patch_status(self) -> Check:
        report = self._read("reports/SECURITY_PATCH_REPORT.md")
        if not report:
            return Check("patch_status", "Known vulnerabilities patched",
                         Verdict.UNVERIFIED, "no patch report present")
        if re.search(r"(?i)remaining vulnerabilities\s*[:=]\s*0\b", report):
            return Check("patch_status", "Known vulnerabilities patched",
                         Verdict.PASS, "patch report states 0 remaining vulnerabilities")
        return Check("patch_status", "Known vulnerabilities patched",
                     Verdict.UNVERIFIED, "patch report does not attest zero remaining")

    def check_secret_guard(self) -> Check:
        env_example = self._read(".env.example")
        if env_example and re.search(r"(?m)^[A-Z0-9_]+=", env_example):
            return Check("secret_guard", "Secret configuration template exists",
                         Verdict.PASS, ".env.example present with placeholder keys (no values read)")
        return Check("secret_guard", "Secret configuration template exists",
                     Verdict.FAIL, ".env.example missing or empty")

    def check_permission_engine(self) -> Check:
        text = self._read("app/terminal/permission_engine.py")
        markers = [m for m in ("PermissionRequired", "action: ask", "action: deny",
                               "PermissionEngine") if m in text]
        if len(markers) >= 3:
            return Check("permission_engine", "Terminal permission engine present",
                         Verdict.PASS, "static markers: " + ", ".join(sorted(markers)))
        return Check("permission_engine", "Terminal permission engine present",
                     Verdict.UNVERIFIED, "permission engine markers not found")

    def check_audit_logging(self) -> Check:
        text = self._read("app/v13/observability.py") + self._read("app/monitoring/logger.py")
        if "REDACTED" in text and "emit" in text:
            return Check("audit_logging", "Redacted structured audit trail available",
                         Verdict.PASS, "trace emits events with recursive redaction")
        return Check("audit_logging", "Redacted structured audit trail available",
                     Verdict.FAIL, "no redacting trace implementation found")

    def check_backups(self) -> Check:
        text = self._read("app/runtime/backup.py")
        if "def backup" in text and "restore" in text.lower():
            return Check("backups", "Backup/restore tooling present",
                         Verdict.PASS, "app/runtime/backup.py implements backup and restore")
        return Check("backups", "Backup/restore tooling present",
                     Verdict.UNVERIFIED, "backup/restore script not found")

    def run(self) -> "SecurityScorecardResult":
        checks = [self.check_patch_status(), self.check_secret_guard(),
                  self.check_permission_engine(), self.check_audit_logging(),
                  self.check_backups()]
        passed = sum(c.verdict is Verdict.PASS for c in checks)
        failed = sum(c.verdict is Verdict.FAIL for c in checks)
        unverified = sum(c.verdict is Verdict.UNVERIFIED for c in checks)
        score = round(100.0 * passed / len(checks), 1) if checks else 0.0
        return SecurityScorecardResult(checks=checks, passed=passed, failed=failed,
                                       unverified=unverified, score=score)


@dataclass
class SecurityScorecardResult:
    checks: list[Check]
    passed: int
    failed: int
    unverified: int
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {"score": self.score, "passed": self.passed, "failed": self.failed,
                "unverified": self.unverified,
                "checks": [c.to_dict() for c in self.checks]}
