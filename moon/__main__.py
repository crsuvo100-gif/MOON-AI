"""MOON-AI top-level command-line entry point for ``python -m MOON-AI``.

MOON-AI is a single-package project (all logic lives under ``app``); this
package supplies the documented top-level entry points:

- ``python -m MOON-AI``               -> MOON-AI Terminal REPL (default)
- ``python -m MOON-AI terminal``      -> MOON-AI Terminal REPL (explicit)
- ``python -m MOON-AI run <task>``    -> CLI single-task runner
- ``python -m MOON-AI models``        -> pre-pull per-agent models
- ``python -m MOON-AI doctor|status|...`` -> CLI subcommands

Real CLI dispatch lives in ``main.py``.  This module reproduces the
subparser construction and the dispatch from ``main.main()`` (lines
~442-525) so that the README-documented ``python -m MOON-AI`` conventions
behave identically to ``moon`` / ``moon-terminal``, without modifying
``main.py`` or the installed console scripts.  The terminal REPL is the
default when no subcommand is given, matching the documented behaviour.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)

if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Ensure the venv site-packages is importable when this file is run with an
# explicit interpreter path from outside the virtual environment.
if os.path.isdir(os.path.join(_PROJECT_ROOT, ".venv")):
    _VENV_SITE = os.path.abspath(
        os.path.join(_PROJECT_ROOT, ".venv", "lib",
                     sys.version.split()[0], "site-packages"))
    if _VENV_SITE not in sys.path:
        sys.path.insert(0, _VENV_SITE)

# Decontaminate foreign-venv PYTHONPATH before any other import.
import app.config.env_guard  # noqa: F401

import argparse
import asyncio
import sys
import moon.build as build_mod

# Import the real CLI MODULE via its own env_guard, so a foreign-venv
# PYTHONPATH cannot shadow the project's own ``app`` package and the
# module-level names (ArgumentParser, _run, _prefetch_models, ...) stay
# importable via ``main``.
import main as _real_main  # the file main.py (a module), not the function

# The REPL is imported lazily for the default/terminal case only.
from app.terminal.repl import main as repl_main  # noqa: E402 (after env guard)


def _build_parser() -> argparse.ArgumentParser:
    # Mirror of main.py: std argparse with the same subcommands and help
    # text so `python -m MOON-AI -h` matches the console-script help.
    ap = argparse.ArgumentParser(prog="moon", description="Standalone AI Agent")
    sub = ap.add_subparsers(dest="cmd")
    run_p = sub.add_parser("run", help="Run a single task via LLM, or launch MOON-AIscope TUI if no task given")
    run_p.add_argument("task", nargs="?", default=None, help="Task to run (omit to launch the terminal)")
    run_p.add_argument("--task", dest="task_flag", default=None, help="Task to run (omit to launch the terminal)")
    run_p.add_argument("--agent", default=None, help="Agent name to run the task with")
    sub.add_parser("models", help="Pre-pull all per-agent preferred models so agents are ready")
    # Single terminal interface: Hermes-style Textual TUI (moonscope).
    #   MOON-AI / MOON-AI terminal / MOON-AI run  ->  Hermes-style TUI (moonscope)
    #   MOON-AI cli  ->  readline REPL (fallback, Hermes-feature-rich)
    #   MOON-AI terminal-moon  ->  standalone MOON-AI Terminal (terminal_moon/ sub-project)
    sub.add_parser("terminal", help="Interactive MOON-AI Terminal REPL (brain-connected)")
    sub.add_parser("telegram", help="Launch MOON-AI's Telegram bot listener (polling)")
    sub.add_parser("doctor", help="Health check: Python/deps/config/DB/agents/tools/model/git")
    sub.add_parser("status", help="Check the running MOON-AI backend health endpoint")
    sub.add_parser("backup", help="Snapshot runtime data into backups/ (cross-platform)")
    sub.add_parser("restore", help="Restore a backups/moon_<timestamp> snapshot")
    sub.add_parser("install", help="Run the Python bootstrap installer (venv + deps + models)")
    sub.add_parser("setup", help="First-run setup wizard (configure .env, then install)")
    sub.add_parser("uninstall", help="Remove MOON-AI auto-start wiring (launcher, services, desktop)")
    sub.add_parser("update", help="Safe update: git pull --ff-only + pip install -e . --upgrade")
    sub.add_parser("version", help="Print MOON-AI version")
    build_p = sub.add_parser("build", help="Scaffold a complete project (VS Code + Makefile + Dockerfile + hermes-acp)")
    build_p.add_argument("project_dir", nargs="?", default=".", help="Project directory to scaffold (default: current dir)")
    build_p.add_argument("--lang", default=None, help="Override language detection (python|node|rust|go|cpp|java)")
    build_p.add_argument("--out", default=None, help="Output directory (default: project dir)")
    build_p.add_argument("--force", action="store_true", help="Overwrite existing generated files")
    return ap


def _run_terminal() -> int:
    repl_main()
    return 0


def _cmd_run(args) -> int:
    task = args.task or args.task_flag
    if task:
        asyncio.run(_real_main._run(task, args.agent))
        return 0
    print("No task given. Use: MOON-AI run \"<task>\" or MOON-AI <subcommand>", file=sys.stderr)
    return 1


def _cmd_models() -> int:
    asyncio.run(_real_main._prefetch_models())
    return 0


def _cmd_terminal() -> int:
    return _run_terminal()


def _cmd_telegram() -> int:
    from app.services.telegram_bot import main as _tg_main
    raise SystemExit(_tg_main())


def _dispatch(args) -> int:
    if args.cmd == "run":
        return _cmd_run(args)
    if args.cmd == "models":
        return _cmd_models()
    if args.cmd == "terminal":
        return _cmd_terminal()
    if args.cmd == "telegram":
        return _cmd_telegram()
    if args.cmd == "version":
        _real_main._cmd_version()
        return 0
    if args.cmd == "build":
        return _cmd_build(args)
    if args.cmd == "status":
        raise SystemExit(_real_main._cmd_status())
    if args.cmd == "doctor":
        # Was advertised by the subparser but had no dispatch branch, so
        # `moon doctor` silently printed help instead of running the check.
        raise SystemExit(_real_main._cmd_doctor())
    if args.cmd == "backup":
        raise SystemExit(_real_main._cmd_backup())
    if args.cmd == "restore":
        raise SystemExit(_real_main._cmd_restore())
    if args.cmd == "install":
        raise SystemExit(_real_main._cmd_install())
    if args.cmd == "setup":
        raise SystemExit(_real_main._cmd_setup())
    if args.cmd == "uninstall":
        raise SystemExit(_real_main._cmd_uninstall())
    if args.cmd == "update":
        raise SystemExit(_real_main._cmd_update())
    # No/unknown subcommand -> help
    argparse.ArgumentParser(prog="moon", description="Standalone AI Agent").print_help()
    return 0


def _cmd_build(args) -> int:
    # Scaffold a complete project: VS Code config + Makefile + Dockerfile + hermes-acp wiring
    project_dir = args.project_dir
    if project_dir is None:
        project_dir = "."
    lang = args.lang or build_mod.detect_language(project_dir)
    result = build_mod.scaffold(project_dir, lang)
    print(f"[MOON-AI] built '{result.language}' project in {result.project}")
    print(f"[MOON-AI] generated {result.num_files} file(s)")
    if result.notes:
        print("NOTES:")
        for n in result.notes:
            print(f"    - {n}")
    return 0


def main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    # README documents `python -m MOON-AI` (no args) as the default terminal.
    if args.cmd in (None, "terminal"):
        return _run_terminal()
    return _dispatch(args)


def _main() -> None:
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        sys.stderr.write("\nMOON-AI interrupted by user.\n")
        raise SystemExit(130)


if __name__ == "__main__":
    _main()
