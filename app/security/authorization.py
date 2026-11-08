"""authorization.py -- authorization gate for active security operations.

MOON-AI is a capable defensive + offensive cyber agent. To stay legitimate, any
ACTIVE operation (scanning, exploiting, probing) against a target REQUIRES that
the target be authorized: either listed in AUTHORIZED_TARGETS (env) or
explicitly confirmed by the operator at runtime. Passive/defensive analysis of
material the user already provides (logs, a file, their own config) never
requires authorization.

This is the same authorization model used by professional red-team tooling
(nmap/Nessus/Metasploit are dual-use and legal only on authorized targets).
"""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass


# Targets the operator owns / is authorized to test. Comma-separated hosts or
# CIDRs in .env (AUTHORIZED_TARGETS). Network locality does not imply consent.
def _authorized_set() -> set[str]:
    raw = os.environ.get("AUTHORIZED_TARGETS", "")
    return {t.strip().lower().rstrip(".") for t in raw.split(",") if t.strip()}


@dataclass
class AuthDecision:
    allowed: bool
    reason: str


def is_authorized(target: str) -> AuthDecision:
    t = (target or "").strip().lower().rstrip(".")
    if not t:
        return AuthDecision(False, "empty target")
    authorized = _authorized_set()
    if t in authorized:
        return AuthDecision(True, "explicitly authorized (AUTHORIZED_TARGETS)")
    try:
        address = ipaddress.ip_address(t.strip("[]"))
    except ValueError:
        address = None
    if address is not None:
        for entry in authorized:
            try:
                if address in ipaddress.ip_network(entry, strict=False):
                    return AuthDecision(True, "address is within an authorized CIDR")
            except ValueError:
                continue
    return AuthDecision(False, "target not in AUTHORIZED_TARGETS; confirm ownership before active ops")


def require_auth(target: str, *, confirmed: bool = False) -> AuthDecision:
    """Active-op gate. `confirmed` is set when the operator explicitly approves."""
    if confirmed is True:
        return AuthDecision(True, "operator confirmed authorization at runtime")
    return is_authorized(target)
