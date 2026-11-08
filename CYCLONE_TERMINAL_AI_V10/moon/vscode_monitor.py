"""moon/vscode_monitor.py -- VS Code monitoring protocol runner.

This module is the entry point for starting the VS Code workflow monitoring
protocol. It connects the MOON-AI terminal workflow with the VS Code editor
through the hermes acp protocol.

Usage:
    python -m moon.vscode_monitor run          # run one monitoring cycle and exit
    python -m moon.vscode_monitor daemon       # run as a persistent monitor
    python -m moon.vscode_monitor status       # show current monitor status
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Ensure the project root is on sys.path
PROJECT_ROOT = Path("/home/meow/Projects/MOON/CYCLONE_TERMINAL_AI_V10")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [moon.vscode_monitor] %(levelname)s %(message)s",
)
logger = logging.getLogger("moon.vscode_monitor")

from app.bridge.vscode_workflow_monitor import MonitorResult, WorkflowState
from app.bridge.vscode_bridge import (
    check_hermes_acp_running,
    probe_project_files,
    run_vscode_task,
    write_bridge_state,
)
from app.bridge.vscode_workflow_monitor import Fixer, scan_vscode_configs


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

def cmd_run(project_root: Path) -> int:
    """Run one monitoring cycle and print the result."""
    logger.info("running VS Code workflow monitor (single cycle)")

    # Step 1: scan VS Code configs
    state = scan_vscode_configs(project_root)

    # Step 2: probe hermes acp
    hermes_ok, pid = check_hermes_acp_running(project_root)
    state.hermes_acp_running = hermes_ok
    state.hermes_acp_pid = pid

    # Step 3: apply fixes
    applied = Fixer.apply_all(project_root)

    # Step 4: write bridge state for the editor
    bridge_state = {
        "checked_at": state.checked_at,
        "healthy": state.is_healthy,
        "hermes_acp_running": hermes_ok,
        "missing_files": state.missing_files,
        "invalid_configs": state.invalid_configs,
        "errors": state.errors,
        "applied_fixes": applied,
    }
    write_bridge_state(project_root, bridge_state)

    # Step 5: print summary
    result = {
        "project_root": str(project_root),
        "healthy": state.is_healthy,
        "hermes_acp_running": hermes_ok,
        "missing_files": state.missing_files,
        "invalid_configs": state.invalid_configs,
        "errors": state.errors,
        "applied_fixes": applied,
        "details": state.to_dict(),
    }
    print(json.dumps(result, indent=2, default=str))

    if state.is_healthy:
        logger.info("monitor: project is healthy")
    else:
        logger.warning("monitor: project has issues (see above)")
    return 0 if state.is_healthy else 1


def cmd_daemon(project_root: Path) -> int:
    """Run the monitor as a persistent daemon, checking every N seconds."""
    parser = argparse.ArgumentParser(description="VS Code monitor daemon")
    parser.add_argument("--interval", type=int, default=30,
                        help="seconds between checks (default: 30)")
    parser.add_argument("--once", action="store_true",
                        help="run one cycle then exit (for testing)")
    args = parser.parse_args()

    logger.info("starting VS Code workflow monitor daemon (interval=%ds)", args.interval)

    cycle = 0
    while True:
        cycle += 1
        logger.info("cycle %d: probing VS Code workflow...", cycle)
        try:
            from app.bridge.vscode_workflow_monitor import VscodeWorkflowMonitor
            monitor = VscodeWorkflowMonitor(project_root)
            result = monitor.run_cycle()
            logger.info(
                "cycle %d: healthy=%s, fixes=%d, hermes_acp=%s",
                cycle, result.healthy, len(result.applied_fixes),
                result.state.hermes_acp_running,
            )
        except Exception as exc:
            logger.exception("cycle %d: monitor error: %s", cycle, exc)

        if args.once:
            break
        import time
        time.sleep(args.interval)

    return 0


def cmd_status(project_root: Path) -> int:
    """Show current VS Code monitor status (no new probe)."""
    from app.bridge.vscode_bridge import read_bridge_state
    bridge = read_bridge_state(project_root)
    print(json.dumps(bridge, indent=2, default=str))
    return 0


def cmd_probe(project_root: Path) -> int:
    """Run a bare probe (no fixes) and return raw project state."""
    from app.bridge.vscode_workflow_monitor import WorkflowState
    project_files = probe_project_files(project_root)
    print(json.dumps(project_files, indent=2, default=str))
    return 0


def cmd_task(label: str, project_root: Path) -> int:
    """Run a MOON task as if from the VS Code task runner."""
    result = run_vscode_task(label, project_root)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("ok") else 1


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="VS Code workflow monitoring protocol (MOON-AI)",
        prog="moon vscode_monitor",
    )
    parser.add_argument(
        "command",
        choices=["run", "daemon", "status", "probe", "task"],
        help="the monitoring command to run",
    )
    parser.add_argument(
        "--project-root", type=Path,
        default=PROJECT_ROOT,
        help="path to the MOON project root (default: CYCLONE_TERMINAL_AI_V10)",
    )
    parser.add_argument(
        "--interval", type=int, default=30,
        help="daemon check interval in seconds (default: 30)",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="run a single cycle and exit (for run/daemon)",
    )
    args = parser.parse_args(argv)

    commands = {
        "run": lambda: cmd_run(args.project_root),
        "daemon": lambda: cmd_daemon(args.project_root),
        "status": lambda: cmd_status(args.project_root),
        "probe": lambda: cmd_probe(args.project_root),
        "task": lambda: cmd_task(args.command, args.project_root),  # type: ignore
    }

    try:
        return commands[args.command]()
    except KeyboardInterrupt:
        logger.info("monitor interrupted by user")
        return 130


if __name__ == "__main__":
    sys.exit(main())
