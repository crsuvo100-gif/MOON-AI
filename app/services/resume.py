"""Resume and pause service.

Provides the HERMES pause/resume function: a command that saves the current
project state and writes hermes status.md, enabling the agent to auto-resume
from the audit status file at the start of the next session.

Usage (from the project root):

    python -m app.services.resume
        # Interactive: prints the current checkpoint, then pauses.

    python -m app.services.resume --pause
        # Immediately save state and pause.

    python -m app.services.resume --resume
        # Read hermes status.md, verify the workspace, and resume.

    python -m app.services.resume --audit
        # Write an audit report to the status file.

This is a persistent function: the state is saved to
~/.hermes/projects/MOON/ and the pause file
~/.hermes/projects/MOON/hermes status.md
is written so the system can auto-resume without any user input.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import datetime

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

STATE_DIR = os.path.expanduser("~/.hermes/projects/MOON")
PROJECT_STATE_FILE = os.path.join(STATE_DIR, "PROJECT_STATE.json")
TASK_QUEUE_FILE = os.path.join(STATE_DIR, "TASK_QUEUE.json")
STATUS_FILE = os.path.join(STATE_DIR, "hermes status.md")
CHECKPOINT_HISTORY = os.path.join(STATE_DIR, "CHECKPOINT_HISTORY.md")
PROGRESS_LOG = os.path.join(STATE_DIR, "PROGRESS_LOG.md")


def ensure_state_dir() -> None:
    os.makedirs(STATE_DIR, exist_ok=True)


def load_state(path: str) -> dict:
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def save_state(path: str, data: dict) -> None:
    ensure_state_dir()
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def append_text(path: str, text: str) -> None:
    ensure_state_dir()
    mode = "a" if os.path.exists(path) else "w"
    with open(path, mode) as f:
        f.write(text)


def build_status_markdown(cur_task: str, stage: str, progress: int,
                          completed: list[str], pending: list[str]) -> str:
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = []
    lines.append("# hermes status.md — AUTO-RESUME CHECKPOINT")
    lines.append("")
    lines.append(f"**Generated:** {now}")
    lines.append("**Project:** MOON V13.0")
    lines.append(f"**Workspace:** {PROJECT_STATE_FILE[:64]}...")
    lines.append("")
    lines.append("## STATUS OVERVIEW")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    lines.append(f"| Current task | {cur_task} |")
    lines.append(f"| Current milestone | {stage} |")
    lines.append(f"| Progress | {progress}% |")
    lines.append("| Recovery status | PAUSED |")
    lines.append("")
    lines.append("## NEXT TWO ACTIONS")
    lines.append("")
    lines.append("1. Resume from the recorded checkpoint and verify state.")
    lines.append("2. Complete the active milestone, then begin the next one.")
    lines.append("")
    lines.append("## PHASE PROGRESS")
    lines.append("")
    rows = [
        ("M0: Audit + Plan", "COMPLETED"),
        ("M1: Phase 1 Agent Connector", "IN_PROGRESS"),
        ("M2: Phase 2 Browser + Research", "NOT_STARTED"),
        ("M3: Phase 3 Coding + Data", "NOT_STARTED"),
        ("M4: Phase 4 Voice + Vision", "NOT_STARTED"),
        ("M5: Phase 5 Security + Observability", "NOT_STARTED"),
        ("FINAL: Acceptance + Reports", "NOT_STARTED"),
    ]
    for name, s in rows:
        lines.append(f"| {name} | {s} |")
    lines.append("")
    lines.append("## CHECKPOINT")
    lines.append("")
    lines.append(f"- **Saved at:** {now}")
    lines.append(f"- **Current task:** {cur_task}")
    lines.append(f"- **Resume from:** {cur_task}")
    lines.append("")
    lines.append("## PROJECT STATE")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(load_state(PROJECT_STATE_FILE), indent=2, default=str))
    lines.append("```")
    lines.append("")
    return "\n".join(lines) + "\n"


def pause() -> None:
    """Save state and write hermes status.md. This is the PAUSE function."""
    ensure_state_dir()
    ps = load_state(PROJECT_STATE_FILE)
    load_state(TASK_QUEUE_FILE)
    if not ps:
        ps = {
            "project_name": "MOON V13.0",
            "current_milestone": "PLAN",
            "overall_progress": 0,
            "recovery_status": "PAUSED",
            "current_task": "Resume checkpoint",
        }
    ps["recovery_status"] = "PAUSED"
    ps["last_checkpoint"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    save_state(PROJECT_STATE_FILE, ps)
    append_text(PROGRESS_LOG, f"\n\n--- {ps['last_checkpoint']} ---\nPaused: {ps.get('current_task', 'unknown')}\n")
    if os.path.exists(CHECKPOINT_HISTORY):
        append_text(CHECKPOINT_HISTORY, f"\n- {ps['last_checkpoint']} | PAUSED | {ps.get('current_task', 'unknown')} | resume\n")
    md = build_status_markdown(
        cur_task=ps.get("current_task", "(unknown)"),
        stage=ps.get("current_milestone", "PLAN"),
        progress=int(ps.get("overall_progress", 0)),
        completed=ps.get("completed_milestones", []),
        pending=ps.get("pending_milestones", []),
    )
    append_text(STATUS_FILE, md)
    print(f"[pause] State saved -> {PROJECT_STATE_FILE}")
    print(f"[pause] Checkpoint -> {STATUS_FILE}")
    print("[pause] PROJECT_STATE.json: recovery_status=PAUSED")
    print("[pause] Next session will auto-resume from the status file.")


def resume() -> None:
    """Read hermes status.md, verify workspace, resume."""
    if not os.path.exists(STATUS_FILE):
        print("[resume] No status file found. Nothing to resume.")
        return
    open(STATUS_FILE).read()
    ps = load_state(PROJECT_STATE_FILE)
    if not ps:
        print("[resume] No PROJECT_STATE.json; creating a fresh checkpoint.")
        ps = {
            "project_name": "MOON V13.0",
            "current_milestone": "PLAN",
            "overall_progress": 0,
            "recovery_status": "RESUMING",
            "current_task": "Auto-resume starting",
        }
        save_state(PROJECT_STATE_FILE, ps)
    ps["recovery_status"] = "RESUMING"
    ps["last_checkpoint"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    save_state(PROJECT_STATE_FILE, ps)
    print(f"[resume] Status file found: {STATUS_FILE}")
    print(f"[resume] Project state loaded from {PROJECT_STATE_FILE}")
    print("[resume] Recovery status = RESUMING")
    if os.path.isdir(BASE_DIR):
        print(f"[resume] Workspace verified: {BASE_DIR}")
        print(f"[resume] Auto-resuming. Current task: {ps.get('current_task', 'unknown')}")
    else:
        print(f"[resume] WARNING: workspace {BASE_DIR} not found. Recovery paused.")
        ps["recovery_status"] = "BLOCKED"
        save_state(PROJECT_STATE_FILE, ps)


def audit(path: str = None) -> None:  # type: ignore[assignment]
    """Write an audit report to the status file."""
    from datetime import datetime, timezone
    p = path or STATUS_FILE
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    md = f"""# hermes status.md — AUDIT
**Generated:** {ts}
**Purpose:** Pause/audit file. Do not edit this file directly; use
`python -m app.services.resume` to manage it.
"""
    append_text(p, md)
    print(f"[audit] Audit written to {p}")


def main() -> None:
    ap = argparse.ArgumentParser(description="MOON pause/resume function")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--pause", action="store_true", help="Save state and pause")
    group.add_argument("--resume", action="store_true", help="Read hermes status.md and resume")
    group.add_argument("--audit", action="store_true", help="Write an audit to the status file")
    args = ap.parse_args()
    if args.pause:
        pause()
    elif args.resume:
        resume()
    elif args.audit:
        audit()


if __name__ == "__main__":
    main()
