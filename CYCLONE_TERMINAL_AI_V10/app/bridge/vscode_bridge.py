"""VS Code Bridge -- connects the MOON-AI terminal workflow with the VS Code
editor through the hermes acp protocol.

This module is the in-editor monitoring surface: it reads the same .vscode/
config files the editor consumes, probes the hermes acp server, and reports
state back through the same protocol channel.

The bridge is designed to be imported by the MOON runtime or run standalone
as a monitoring daemon for the `projects.cause` workflow.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("vscode_bridge")

# Default relative to the MOON project root
DEFAULT_PROJECT_ROOT = Path("/home/meow/Projects/MOON/CYCLONE_TERMINAL_AI_V10")

# ---------------------------------------------------------------------------
# Health check helpers
# ---------------------------------------------------------------------------

def check_hermes_acp_running(project_root: Path) -> tuple[bool, int | None]:
    """Probe for a running hermes acp server in the given workspace."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "hermes-acp"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            for pid_str in result.stdout.strip().splitlines():
                pid_str = pid_str.strip()
                if not pid_str.isdigit():
                    continue
                pid = int(pid_str)
                try:
                    with open(f"/proc/{pid}/cmdline", "rb") as fh:
                        cmdline = fh.read().decode(errors="ignore")
                    if "hermes-acp" in cmdline or "hermes acp" in cmdline:
                        return True, pid
                except Exception:
                    continue
            return True, None  # found at least one process
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return False, None


def probe_project_files(project_root: Path) -> dict[str, Any]:
    """Check presence of critical project files."""
    checks = {
        "project_root_exists": project_root.is_dir(),
        "moon_terminal": (project_root / "moon_terminal.py").is_file(),
        "main_py": (project_root / "main.py").is_file(),
        "moon_dir": (project_root / "moon").is_dir(),
        "moon_tools": (project_root / "moon" / "tools").is_dir(),
        "vscode_dir": (project_root / ".vscode").is_dir(),
    }
    # check vscode config files
    vscode = project_root / ".vscode"
    for fname in ["settings.json", "launch.json", "tasks.json", "extensions.json"]:
        checks[f"vscode_{fname}"] = (vscode / fname).is_file()

    # probe hermes acp
    hermes_ok, _ = check_hermes_acp_running(project_root)
    checks["hermes_acp_running"] = hermes_ok

    return checks


# ---------------------------------------------------------------------------
# Bridge state reporter
# ---------------------------------------------------------------------------

def write_bridge_state(project_root: Path, state: dict[str, Any]) -> None:
    """Write the VS Code bridge state file that the editor can read."""
    vscode = project_root / ".vscode"
    vscode.mkdir(parents=True, exist_ok=True)
    bridge_state = {
        "bridge_version": "1.0.0",
        "monitored_project": "projects.cause",
        "last_check": state.get("checked_at", None),
        "healthy": state.get("healthy", False),
        "hermes_acp_running": state.get("hermes_acp_running", False),
        "missing_files": state.get("missing_files", []),
        "invalid_configs": state.get("invalid_configs", []),
        "errors": state.get("errors", []),
    }
    (vscode / ".vscode_bridge_state.json").write_text(
        json.dumps(bridge_state, indent=2)
    )


def read_bridge_state(project_root: Path) -> dict[str, Any]:
    """Read bridge state written by the monitor."""
    path = project_root / ".vscode" / ".vscode_bridge_state.json"
    if path.is_file():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {}


# ---------------------------------------------------------------------------
# VS Code task runner (runs MOON tasks inside the editor's task system)
# ---------------------------------------------------------------------------

def run_vscode_task(label: str, project_root: Path) -> dict[str, Any]:
    """Invoke a VS Code task by label (mirrors 'Tasks: Run Task' in the editor)."""
    from app.bridge.vscode_workflow_monitor import scan_vscode_configs

    labels = {
        "MOON: Build & Run": ["make", "run"],
        "MOON: Test": ["make", "test"],
        "MOON: Verify": ["make", "live"],
        "hermes build": ["hermes", "acp"],
    }

    if label not in labels:
        return {"ok": False, "error": f"unknown task label: {label}"}

    cmd = labels[label]
    try:
        result = subprocess.run(
            cmd,
            cwd=str(project_root),
            capture_output=True, text=True, timeout=120,
        )
        return {
            "ok": result.returncode == 0,
            "label": label,
            "returncode": result.returncode,
            "stdout": result.stdout[-500:],
            "stderr": result.stderr[-500:],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "label": label, "error": "timed out"}


# ---------------------------------------------------------------------------
# Protocol monitor (hermes acp protocol telemetry)
# ---------------------------------------------------------------------------

class ProtocolMonitor:
    """Observes hermes acp protocol events and writes structured telemetry.

    The hermes acp protocol uses stdio; a background process reads the
    hermes acp server's stdout/stderr and records events to a JSONL log.
    """

    def __init__(self, log_file: str | None = None):
        self.log_file = log_file or \
            str(Path.home() / ".moon" / "vscode_monitors" / "acp_protocol.log")
        Path(self.log_file).parent.mkdir(parents=True, exist_ok=True)
        self._process: subprocess.Popen | None = None

    def start(self, project_root: Path) -> None:
        """Start monitoring the hermes acp protocol for the given project."""
        if self._process is not None and self._process.poll() is None:
            return  # already running

        hermes_acp = os.path.expanduser(
            "~/.hermes/hermes-agent/.hermes/bin/hermes-acp"
        )
        cmd = [hermes_acp]
        logger.info("starting hermes acp monitor: %s", " ".join(cmd))
        self._process = subprocess.Popen(
            cmd,
            cwd=str(project_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        # Note: reading from the pipe is best-effort; a full protocol
        # implementation would use proper async I/O or subprocess.communicate().
        # Here we log the startup event and keep the handle for lifecycle.
        if self._process.stdout:
            logger.info("hermes acp monitor started (pid=%d)", self._process.pid)

    def stop(self) -> None:
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "type": event_type,
            "data": data,
            "pty_host": os.environ.get("MOON_PTY_HOST", ""),
        }
        Path(self.log_file).parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_file, "a") as fh:
            fh.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# Entry point: run the full monitoring cycle
# ---------------------------------------------------------------------------

def run_monitoring_cycle(project_root: Path | None = None) -> dict[str, Any]:
    """Run a single monitoring cycle and return the result dict."""
    from app.bridge.vscode_workflow_monitor import (
        MonitorResult, Fixer, scan_vscode_configs, WorkflowState
    )

    root = project_root or DEFAULT_PROJECT_ROOT
    if not root.is_dir():
        return {"error": f"project root not found: {root}"}

    monitor = MonitorResult(
        state=WorkflowState(project_root=root),
        applied_fixes=Fixer.apply_all(root),
    )
    monitor.state = scan_vscode_configs(root)

    # Probe hermes acp separately to keep the result accurate
    hermes_ok, pid = check_hermes_acp_running(root)
    monitor.state.hermes_acp_running = hermes_ok
    monitor.state.hermes_acp_pid = pid

    # Write bridge state for the editor to consume
    bridge_state = {
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "healthy": monitor.state.is_healthy,
        "hermes_acp_running": hermes_ok,
        "missing_files": monitor.state.missing_files,
        "invalid_configs": monitor.state.invalid_configs,
        "errors": monitor.state.errors,
        "applied_fixes": monitor.applied_fixes,
    }
    write_bridge_state(root, bridge_state)

    return {
        "project_root": str(root),
        "healthy": monitor.state.is_healthy,
        "hermes_acp_running": hermes_ok,
        "missing_files": monitor.state.missing_files,
        "invalid_configs": monitor.state.invalid_configs,
        "errors": monitor.state.errors,
        "applied_fixes": monitor.applied_fixes,
        "state": monitor.state.to_dict(),
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="VS Code workflow monitor")
    parser.add_argument("--project-root", type=Path, default=None)
    parser.add_argument("--once", action="store_true", help="run one cycle and exit")
    parser.add_argument("--daemon", action="store_true", help="run as a monitoring daemon")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    result = run_monitoring_cycle(args.project_root)
    print(json.dumps(result, indent=2, default=str))
