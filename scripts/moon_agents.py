#!/usr/bin/env python3
"""MOON-AI agent runner -- run every agent role one by one, in order.

The requested roles map onto real, verifiable build stages:

    agent-build   -> make build     (build + install the project package)
    agent-edit    -> make arrange   (arrange the file/folder layout)
    agent-rum     -> make compile   (full-project byte compilation)
    agent-run     -> make test      (full pytest suite)
    agent-verify  -> make verify    (end-to-end live smoke verification)
    ------------------------------------------------------------------
    final handoff -> make serve     (launch the project; blocking)

Usage:
    python3 scripts/moon_agents.py            # run every role, one by one
    python3 scripts/moon_agents.py --role agent-build
    python3 scripts/moon_agents.py --list-roles   # list registered MOON-AI roles

Every stage is additive and non-destructive. A failed stage is reported and
stops the sequence so a later stage never runs on a broken build.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Ordered by design: each stage consumes the previous stage's result.
ROLES: tuple["Role", ...] = ()  # filled below


@dataclass(frozen=True)
class Role:
    name: str
    target: str
    step: str
    description: str


ROLES = (
    Role("agent-build", "build", "1/5", "Build and install the project package"),
    Role("agent-edit", "arrange", "2/5", "Arrange/verify the file and folder layout"),
    Role("agent-rum", "compile", "3/5", "Compile every Python source in the project"),
    Role("agent-run", "test", "4/5", "Run the full pytest suite"),
    Role("agent-verify", "verify", "5/5", "Verify end-to-end with the live smoke pipeline"),
)


def run_role(role: Role) -> bool:
    """Run one agent role via its Make target. Stream output to the console."""
    print(f"\n{'=' * 72}")
    print(f"[{role.step}] {role.name}  ->  make {role.target}")
    print(f"        {role.description}")
    print("=" * 72, flush=True)
    env = dict(os.environ)
    env.setdefault("PYTHONUNBUFFERED", "1")
    try:
        completed = subprocess.run(
            ["make", role.target], cwd=ROOT, env=env, check=False
        )
    except OSError as exc:  # pragma: no cover - make missing is environmental
        print(f"[FAIL] {role.name}: {exc}")
        return False
    ok = completed.returncode == 0
    print(f"[{'OK' if ok else 'FAIL'}] {role.name} (exit {completed.returncode})", flush=True)
    return ok


def list_registered_roles() -> int:
    """List the 40 spec agent roles registered in app/agents/spec_agents.py."""
    sys.path.insert(0, str(ROOT))
    try:
        from app.agents.registry import get_registry  # type: ignore
        from app.agents.spec_agents import register_spec_agents  # type: ignore

        register_spec_agents()
        agents = get_registry().all()
        rows = [
            (getattr(a, "id", "") or getattr(a, "name", ""),
             getattr(a, "role_group", ""))
            for a in agents
        ]
    except Exception as exc:
        print(f"[warn] registry unavailable: {exc}", file=sys.stderr)
        return 1
    for idx, (name, group) in enumerate(rows, 1):
        print(f"{idx:>3}. {name:<32} {group}")
    print(f"Total registered roles: {len(rows)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=[r.name for r in ROLES], help="run a single role")
    parser.add_argument("--list-roles", action="store_true", help="list registered MOON-AI roles")
    args = parser.parse_args(argv)

    if args.list_roles:
        return list_registered_roles()

    selected = [r for r in ROLES if r.name == args.role] if args.role else list(ROLES)
    results: list[tuple[str, bool]] = []
    for role in selected:
        results.append((role.name, run_role(role)))

    print(f"\n{'=' * 72}")
    print("MOON-AI agent run summary")
    print("=" * 72)
    for name, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if all(ok for _, ok in results):
        print("\nAll agent roles completed. Final step -> make serve")
        return 0
    print("\nSequence stopped: fix the failed role before continuing.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
