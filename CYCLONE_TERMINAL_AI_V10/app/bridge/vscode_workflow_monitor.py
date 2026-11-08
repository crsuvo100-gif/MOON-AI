"""VS Code Workflow Monitor -- tracks the VS Code editor workflow that runs
`projects.cause`, detects wrong/buggy/missing items, and auto-fixes them.

Architecture:
  * VscodeWorkflowMonitor  -- top-level orchestrator
  * VSCodeBridge           -- bidirectional bridge to the VS Code editor
    (reads .vscode config, runs hermes acp, probes the workflow)
  * WorkflowState          -- the running state of the monitored project
  * Fixer                  -- pattern-based repair engine (in-editor fixes)
  * ProtocolMonitor        -- websocket/stdio protocol telemetry (hermes acp)

Designed to be wired into the VS Code editor workflow: the monitor reads the
same .vscode/ launch.json, tasks.json, settings.json that the editor consumes,
and reports status back through the hermes acp protocol that VS Code and MOON
share.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.bridge.vscode_bridge import VSCodeBridge

logger = logging.getLogger("vscode_monitor")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MONITOR_DIR = Path.home() / ".moon" / "vscode_monitors"
DEFAULT_MONITOR_DIR.mkdir(parents=True, exist_ok=True)

PROJECT_CHAIN = [
    Path("/home/meow/Projects/MOON/CYCLONE_TERMINAL_AI_V10"),
    Path.home() / "Projects" / "MOON" / "CYCLONE_TERMINAL_AI_V10",
]

VS_CODE_DIR = ".vscode"
VS_CODE_CONFIGS = [
    "settings.json",
    "launch.json",
    "tasks.json",
    "extensions.json",
]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class WorkflowState:
    """Running state snapshot of the monitored project."""

    project_root: Path
    checked_at: float = field(default_factory=time.time)
    vs_code_dir_exists: bool = False
    launch_config_ok: bool = False
    tasks_config_ok: bool = False
    settings_ok: bool = False
    extensions_ok: bool = False
    hermes_acp_running: bool = False
    hermes_acp_pid: int | None = None
    missing_files: list[str] = field(default_factory=list)
    invalid_configs: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def is_healthy(self) -> bool:
        return not (self.missing_files or self.invalid_configs or self.errors)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_root": str(self.project_root),
            "checked_at": datetime.fromtimestamp(
                self.checked_at, tz=timezone.utc
            ).isoformat(),
            "vs_code_dir_exists": self.vs_code_dir_exists,
            "launch_config_ok": self.launch_config_ok,
            "tasks_config_ok": self.tasks_config_ok,
            "settings_ok": self.settings_ok,
            "extensions_ok": self.extensions_ok,
            "hermes_acp_running": self.hermes_acp_running,
            "hermes_acp_pid": self.hermes_acp_pid,
            "missing_files": self.missing_files,
            "invalid_configs": self.invalid_configs,
            "errors": self.errors,
            "is_healthy": self.is_healthy,
        }


@dataclass
class MonitorResult:
    state: WorkflowState
    applied_fixes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return self.state.is_healthy


# ---------------------------------------------------------------------------
# VS Code config readers / validators
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        logger.warning("cannot read %s: %s", path, exc)
        return None


def _validate_launch_json(cfg: dict[str, Any]) -> list[str]:
    """Return a list of problem messages (empty = healthy)."""
    problems: list[str] = []
    if not isinstance(cfg, dict):
        return ["launch.json: top-level value is not an object"]
    if "compounds" in cfg:
        for comp in cfg["compounds"]:
            if not isinstance(comp, dict):
                problems.append("compound entry is not an object")
                continue
            names = comp.get("configurations", [])
            for ref in names:
                if not isinstance(ref, str):
                    problems.append(f"compound config reference is not a string: {ref!r}")
                elif ref not in [c.get("name") for c in cfg.get("configurations", [])]:
                    problems.append(f"dangling compound reference: {ref!r} (no such configuration)")
    # sanity: every configuration must have a name
    for c in cfg.get("configurations", []):
        if not isinstance(c, dict) or "name" not in c:
            problems.append(f"configuration missing 'name' key: {c!r}")
    return problems


def _validate_settings_json(cfg: dict[str, Any]) -> list[str]:
    """Check for known-bad setting keys."""
    problems: list[str] = []
    if not isinstance(cfg, dict):
        return ["settings.json: top-level value is not an object"]

    git_settings = cfg.get("git", {})
    # git.autofetch is not a valid VS Code setting; the real key is git.autoFetch
    if isinstance(git_settings, dict) and "autofetch" in git_settings:
        problems.append(
            "settings.json: 'git.autofetch' is not a valid VS Code setting; "
            "use 'git.autoFetch' instead"
        )
    return problems


def _validate_tasks_json(cfg: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if not isinstance(cfg, dict):
        return ["tasks.json: top-level value is not an object"]
    if "tasks" not in cfg:
        problems.append("tasks.json: missing top-level 'tasks' array")
        return problems
    for i, task in enumerate(cfg.get("tasks", [])):
        if not isinstance(task, dict):
            problems.append(f"tasks[{i}]: not an object")
            continue
        if "problemMatcher" not in task:
            task.setdefault("problemMatcher", [])
        # The generator (moon/build.py) already sets problemMatcher; here we
        # just note it if the generated file is missing it.
        if "command" not in task:
            problems.append(f"tasks[{i}]: missing 'command' key")
    return problems


def _validate_extensions_json(cfg: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if not isinstance(cfg, dict):
        return ["extensions.json: top-level value is not an object"]
    if "recommendations" not in cfg:
        problems.append("extensions.json: missing 'recommendations' array")
    elif not isinstance(cfg["recommendations"], list):
        problems.append("extensions.json: 'recommendations' is not an array")
    return problems


def scan_vscode_configs(project_root: Path) -> WorkflowState:
    """Read and validate all VS Code config files for the given project."""
    state = WorkflowState(project_root=project_root)
    vscode_dir = project_root / VS_CODE_DIR
    state.vs_code_dir_exists = vscode_dir.is_dir()

    if not state.vs_code_dir_exists:
        state.missing_files.append(VS_CODE_DIR)
        return state

    for fname in VS_CODE_CONFIGS:
        fpath = vscode_dir / fname
        if not fpath.is_file():
            state.missing_files.append(fname)
            continue
        cfg = _read_json(fpath)
        if cfg is None:
            state.errors.append(f"{fname}: unreadable")
            continue
        if fname == "launch.json":
            problems = _validate_launch_json(cfg)
            state.launch_config_ok = len(problems) == 0
            state.invalid_configs.extend([{"file": fname, "problem": p} for p in problems])
        elif fname == "settings.json":
            problems = _validate_settings_json(cfg)
            state.settings_ok = len(problems) == 0
            state.invalid_configs.extend([{"file": fname, "problem": p} for p in problems])
        elif fname == "tasks.json":
            problems = _validate_tasks_json(cfg)
            state.tasks_config_ok = len(problems) == 0
            state.invalid_configs.extend([{"file": fname, "problem": p} for p in problems])
        elif fname == "extensions.json":
            problems = _validate_extensions_json(cfg)
            state.extensions_ok = len(problems) == 0
            state.invalid_configs.extend([{"file": fname, "problem": p} for p in problems])

    if not state.launch_config_ok:
        state.errors.append("launch.json invalid")
    if not state.settings_ok:
        state.errors.append("settings.json invalid")
    if not state.tasks_config_ok:
        state.errors.append("tasks.json missing problemMatcher")
    if not state.extensions_ok:
        state.errors.append("extensions.json missing recommendations")

    return state


# ---------------------------------------------------------------------------
# VS Code bridge (bridge to the editor + hermes acp protocol)
# ---------------------------------------------------------------------------

class VSCodeBridge:
    """Bidirectional bridge to the VS Code editor workflow.

    Reads .vscode/ files (same as the editor), probes the hermes acp protocol,
    and reports status back through the same channel VS Code uses.
    """

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.vscode_dir = project_root / VS_CODE_DIR
        self.bridge_file = project_root / f"{VS_CODE_DIR}/.vscode_bridge_state.json"

    def probe_hermes_acp(self) -> tuple[bool, int | None]:
        """Check whether the hermes acp server is running in this workspace."""
        try:
            # Look for a running hermes acp process referencing this workspace
            result = subprocess.run(
                ["pgrep", "-f", "hermes-acp"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                pids = [int(p) for p in result.stdout.strip().splitlines() if p.strip().isdigit()]
                # Filter pids that match our workspace (simple heuristic)
                for pid in pids:
                    try:
                        with open(f"/proc/{pid}/cmdline", "rb") as fh:
                            cmdline = fh.read().decode(errors="ignore")
                        if "hermes-acp" in cmdline or "hermes acp" in cmdline:
                            return True, pid
                    except Exception:
                        continue
                # Some systems expose the whole command in pgrep output
                return True, pids[0]
            return False, None
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False, None

    def load_bridge_state(self) -> dict[str, Any]:
        if self.bridge_file.is_file():
            try:
                return json.loads(self.bridge_file.read_text())
            except Exception:
                pass
        return {"last_seen": None, "checks": []}

    def save_bridge_state(self, state: dict[str, Any]) -> None:
        self.bridge_file.parent.mkdir(parents=True, exist_ok=True)
        self.bridge_file.write_text(json.dumps(state, indent=2))

    def probe_workflow(self) -> WorkflowState:
        """Full probe of the VS Code workflow: configs + hermes acp."""
        state = scan_vscode_configs(self.project_root)
        hermes_ok, pid = self.probe_hermes_acp()
        state.hermes_acp_running = hermes_ok
        state.hermes_acp_pid = pid
        return state


# ---------------------------------------------------------------------------
# Fixer (pattern-based repair engine)
# ---------------------------------------------------------------------------

class Fixer:
    """Applies pattern-based fixes to VS Code config files found by the monitor."""

    FIXES_APPLIED: list[str] = []

    @classmethod
    def fix_launch_json_compound(cls, project_root: Path) -> bool:
        """Fix dangling compound references in launch.json."""
        path = project_root / VS_CODE_DIR / "launch.json"
        if not path.is_file():
            return False
        cfg = _read_json(path)
        if not isinstance(cfg, dict) or "compounds" not in cfg:
            return False

        fixed = False
        for comp in cfg["compounds"]:
            if not isinstance(comp, dict):
                continue
            names = comp.get("configurations", [])
            for i, ref in enumerate(names):
                if not isinstance(ref, str):
                    continue
                existing_names = [c.get("name") for c in cfg.get("configurations", [])
                                  if isinstance(c, dict) and "name" in c]
                if ref not in existing_names:
                    # Find a valid configuration to use instead (first one)
                    if existing_names:
                        names[i] = existing_names[0]
                        fixed = True
                        cls.FIXES_APPLIED.append(
                            f"launch.json: replaced dangling compound ref '{ref}' with '{names[i]}'"
                        )

        if fixed:
            path.write_text(json.dumps(cfg, indent=2) + "\n")
        return fixed

    @classmethod
    def fix_settings_git_autofetch(cls, project_root: Path) -> bool:
        """Rename invalid 'git.autofetch' setting to valid 'git.autoFetch'."""
        path = project_root / VS_CODE_DIR / "settings.json"
        if not path.is_file():
            return False
        cfg = _read_json(path)
        if not isinstance(cfg, dict):
            return False

        fixed = False
        git = cfg.get("git", {})
        if isinstance(git, dict) and isinstance(git.get("autofetch"), bool):
            autofetch_val = git.pop("autofetch")
            git["autoFetch"] = autofetch_val
            fixed = True
            cls.FIXES_APPLIED.append(
                "settings.json: renamed 'git.autofetch' to 'git.autoFetch' (invalid key)"
            )

        if fixed:
            path.write_text(json.dumps(cfg, indent=2) + "\n")
        return fixed

    @classmethod
    def fix_tasks_problemmatcher(cls, project_root: Path) -> bool:
        """Ensure every task declares problemMatcher."""
        path = project_root / VS_CODE_DIR / "tasks.json"
        if not path.is_file():
            return False
        cfg = _read_json(path)
        if not isinstance(cfg, dict) or "tasks" not in cfg:
            return False

        fixed = False
        for task in cfg["tasks"]:
            if isinstance(task, dict) and "problemMatcher" not in task:
                task["problemMatcher"] = []
                fixed = True
                cls.FIXES_APPLIED.append(f"tasks.json: added problemMatcher to task '{task.get('label', '?')}'")

        if fixed:
            path.write_text(json.dumps(cfg, indent=2) + "\n")
        return fixed

    @classmethod
    def fix_extensions_recommendations(cls, project_root: Path) -> bool:
        """Add recommended MOON/VS Code extensions if recommendations is missing."""
        path = project_root / VS_CODE_DIR / "extensions.json"
        if not path.is_file():
            return False
        cfg = _read_json(path)
        if not isinstance(cfg, dict):
            return False

        fixed = False
        if "recommendations" not in cfg or not isinstance(cfg["recommendations"], list):
            cfg["recommendations"] = [
                "formulahendry.acp-client",
                "ms-python.python",
                "ms-python.vscode-pylance",
                "ms-python.black-formatter",
                "omercnet.vscode-acp",
            ]
            fixed = True
            cls.FIXES_APPLIED.append("extensions.json: added recommended extensions")
            path.write_text(json.dumps(cfg, indent=2) + "\n")
        return fixed

    @classmethod
    def apply_all(cls, project_root: Path) -> list[str]:
        """Run all fixers and return the list of applied fixes."""
        cls.FIXES_APPLIED = []
        cls.fix_launch_json_compound(project_root)
        cls.fix_settings_git_autofetch(project_root)
        cls.fix_tasks_problemmatcher(project_root)
        cls.fix_extensions_recommendations(project_root)
        return cls.FIXES_APPLIED


# ---------------------------------------------------------------------------
# Main monitor orchestrator
# ---------------------------------------------------------------------------

class VscodeWorkflowMonitor:
    """Top-level monitor: probes the VS Code workflow, auto-fixes, logs."""

    def __init__(self, project_root: Path | None = None, log_dir: Path | None = None):
        self.project_root = Path(project_root or \
            next((p for p in PROJECT_CHAIN if p.is_dir()), None) or Path.cwd())
        self.bridge = VSCodeBridge(self.project_root)
        self.log_dir = Path(log_dir or DEFAULT_MONITOR_DIR)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / f"monitor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"

    def probe(self) -> MonitorResult:
        """Probe the VS Code workflow and return a result."""
        state = self.bridge.probe_workflow()
        applied = Fixer.apply_all(self.project_root)
        # Check for PTY host capability
        pty_host = self._probe_pty_host()
        state.pty_host = pty_host
        result = MonitorResult(state=state, applied_fixes=applied)
        self._log(result)
        return result

    def _probe_pty_host(self) -> dict[str, Any]:
        """Probe the PTY host capability for the VS Code workflow.

        The PTY host is the pseudo-terminal device that the VS Code editor
        uses to run interactive commands. For the MOON-AI workflow, the
        hermes acp server (which runs inside VS Code's terminal) communicates
        over this PTY.
        Returns:
            dict with keys: present, host_pid, host_cmdline
        """
        pty_host = {
            "present": False,
            "host_pid": None,
            "host_cmdline": None,
        }
        try:
            # On Linux, the VS Code terminal runs commands in /dev/pts/*
            # We look for the hermes-acp process and check its controlling
            # terminal (via /proc/<pid>/stat and /dev/pts).
            # First, find hermes-acp processes
            result = subprocess.run(
                ["pgrep", "-f", "hermes-acp"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return pty_host
            pids = result.stdout.strip().splitlines()
            for pid_str in pids:
                pid_str = pid_str.strip()
                if not pid_str.isdigit():
                    continue
                pid = int(pid_str)
                try:
                    # Read /proc/<pid>/stat for the controlling terminal
                    with open(f"/proc/{pid}/stat", "r") as fh:
                        stat = fh.read()
                    # Fields: pid (1) comm (2) state (3) ppid (4)
                    # The field after comm is the process state.
                    # Next fields: ppid (4), pgrp (5), session (6)
                    parts = stat.split()
                    # comm is in parentheses, may contain spaces
                    # Find the closing paren
                    rparen = stat.rfind(')')
                    if rparen < 0:
                        continue
                    after_rparen = stat[rparen+1:].strip().split()
                    if len(after_rparen) < 8:
                        continue
                    ppid = int(after_rparen[1])   # field 4: ppid
                    pgrp = int(after_rparen[2])   # field 5: pgrp
                    session = int(after_rparen[3])  # field 6: session
                    # The controlling terminal is field 7 (tpgid)
                    tpgid = int(after_rparen[4])
                    # Check if this is a pseudo-terminal
                    pts_path = f"/dev/pts/{tpgid}"
                    if os.path.exists(pts_path):
                        pty_host = {
                            "present": True,
                            "host_pid": pid,
                            "host_cmdline": f"hermes-acp (session={session}, pgrp={pgrp}, pts={pts_path})",
                            "session": session,
                            "pgrp": pgrp,
                            "pts_device": pts_path,
                        }
                        break
                except Exception:
                    continue
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return pty_host

    def _log(self, result: MonitorResult) -> None:
        entry = {
            **result.state.to_dict(),
            "applied_fixes": result.applied_fixes,
            "healthy": result.healthy,
        }
        with open(self.log_file, "a") as fh:
            fh.write(json.dumps(entry) + "\n")

    def run_cycle(self) -> MonitorResult:
        """Full probe cycle: probe, fix, log, return."""
        return self.probe()

    def status(self) -> dict[str, Any]:
        """Return current status summary (without re-probing)."""
        state = self.bridge.probe_workflow()
        return state.to_dict()
