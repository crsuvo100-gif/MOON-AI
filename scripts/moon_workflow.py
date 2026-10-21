#!/usr/bin/env python3
"""
MOON Workflow Runner -- save-first + auto-build + GitHub-complete.

ALL project tasks / work / builds are first saved into the MOON SOURCE
FOLDER before anything else:

    MOON_SRC = /home/meow/Projects/MOON

After a task finishes (success or failure) the runner:
  1. writes the task result + a timestamped log into MOON_SRC,
  2. asks the user whether to push to GitHub,
  3. if the user says yes AND GitHub is connected, runs `git push`.

This keeps the local source folder as the single source of truth and only
pushes to GitHub after the user explicitly says the project is done.

Usage:
    python3 scripts/moon_workflow.py run "make run"                     # run a cmd
    python3 scripts/moon_workflow.py build                              # make build
    python3 scripts/moon_workflow.py terminal                           # MOON terminal HUD
    python3 scripts/moon_workflow.py test                               # make test
    python3 scripts/moon_workflow.py status                             # show state
"""

import os
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# The SINGLE source folder for everything this project builds.
# ---------------------------------------------------------------------------
MOON_SRC = Path(os.environ.get("MOON_SRC", "/home/meow/Projects/MOON"))

LOG_DIR = MOON_SRC / ".moon_workflow_logs"
META_FILE = MOON_SRC / ".moon_workflow_complete"

# ---------------------------------------------------------------------------
# Save-first: everything (outputs, logs, results) goes into MOON_SRC
# ---------------------------------------------------------------------------
def ensure_src() -> None:
    MOON_SRC.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def save_record(phase: str, payload: str) -> Path:
    """Append a timestamped, JSON-safe record into the MOON source folder."""
    ensure_src()
    ts = time.strftime("%Y%m%d-%H%M%S")
    record = LOG_DIR / f"{phase}_{ts}.log"
    record.write_text(f"=== {phase} @ {ts} ===\n{payload}\n", encoding="utf-8")
    return record


def git_remote_url() -> str | None:
    """Return the GitHub remote URL, or None if not connected."""
    try:
        out = subprocess.run(
            ["git", "-C", str(MOON_SRC), "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return None


def git_push(report: str) -> None:
    """Push to GitHub if connected; otherwise tell the user to connect."""
    url = git_remote_url()
    if not url:
        print("  ! GitHub remote 'origin' is NOT connected.")
        print("    Run: git remote add origin <github-repo-url>   then push.")
        return
    print(f"  Pushing to GitHub (origin -> {url}) ...")
    res = subprocess.run(["git", "-C", str(MOON_SRC), "push", "origin", "main"],
                         capture_output=True, text=True)
    if res.returncode == 0:
        print("  OK: pushed to GitHub.")
    else:
        print(f"  ! git push failed:\n{res.stderr}")


# ---------------------------------------------------------------------------
# The workflow
# ---------------------------------------------------------------------------
def run_workflow(args: list[str]) -> int:
    if not MOON_SRC.exists():
        print(f"MISSING SOURCE FOLDER: {MOON_SRC} -- create it first.")
        return 1

    cmd = args[0] if args else "status"
    rest = args[1:]

    if cmd == "status":
        print(f"MOON source folder : {MOON_SRC}")
        print(f"Workflow logs dir  : {LOG_DIR}")
        print(f"GitHub remote      : {git_remote_url() or 'NOT CONNECTED'}")
        if META_FILE.exists():
            print(f"Last completion    : {META_FILE.read_text(encoding='utf-8').strip()}")
        return 0

    if cmd in ("help", "--help", "-h"):
        print(__doc__)
        return 0

    # ------------------------------------------------------------------
    # Save-first: snapshot the source folder state before the task runs
    # ------------------------------------------------------------------
    before = subprocess.run(
        ["git", "-C", str(MOON_SRC), "status", "--porcelain=v1"],
        capture_output=True, text=True,
    ).stdout

    no_prompt = os.environ.get("MOON_NO_PROMPT", "").lower() in ("1", "true", "yes")

    print(f"MOON_WORKFLOW: running [{cmd}] -> source folder = {MOON_SRC}")
    print("MOON_WORKFLOW: saving to source folder first ...")

    try:
        # Run the requested command, inherited stdio, cwd = source folder.
        res = subprocess.run(rest, cwd=str(MOON_SRC))
    except FileNotFoundError:
        print(f"MOON_WORKFLOW: command not found: {rest[0]}")
        res = None

    after = subprocess.run(
        ["git", "-C", str(MOON_SRC), "status", "--porcelain=v1"],
        capture_output=True, text=True,
    ).stdout

    log = []
    log.append(f"command      : {' '.join(rest)}")
    log.append(f"exit_code    : {res.returncode if res is not None else 'N/A'}")
    log.append(f"cwd          : {MOON_SRC}")
    log.append(f"changed_files: {len(after.splitlines())}")
    if after:
        log.append("changed_files (porcelain):")
        log.extend("  " + l for l in after.splitlines())
    log.append(f"started_at   : {time.strftime('%Y-%m-%d %H:%M:%S')}")
    log.append(f"completed_at : {time.strftime('%Y-%m-%d %H:%M:%S')}")
    record = "\n".join(log)

    save_record("workflow", record)

    if res is not None and res.returncode != 0:
        print(f"\nMOON_WORKFLOW: COMMAND FAILED (exit {res.returncode}).")
        log.append(f"Log saved: {LOG_DIR / ('workflow_' + time.strftime('%Y%m%d-%H%M%S') + '.log')}")
    else:
        print(f"\nMOON_WORKFLOW: OK (exit 0).")

    # ------------------------------------------------------------------
    # After the task is fully completed: ask the user about GitHub push
    # ------------------------------------------------------------------
    if cmd not in ("status", "--help", "-h"):
        print("\nMOON_WORKFLOW: all work saved to source folder.")
        if no_prompt:
            print("  MOON_NO_PROMPT=1 set -> skipping GitHub push prompt.")
        else:
            choice = input("Push to GitHub now? (y/n) [n]: ").strip().lower()
            if choice.startswith("y"):
                git_push(record)
            else:
                print("  Skipped -- you can push later from VS Code / hermes terminal.")

    # Persist a completion marker for the "project fully completed" check
    if cmd in ("build", "run", "terminal", "test", "live"):
        META_FILE.write_text(record + "\n", encoding="utf-8")

    return res.returncode if res is not None else 1


if __name__ == "__main__":
    sys.exit(run_workflow(sys.argv[1:]) or 0)
