"""MOON-AI top-level command-line entry point for ``python -m moon``.

MOON-AI is a single-package project (all logic lives under ``app``); this
package supplies the documented top-level entry points:

- ``python -m moon``                  -> MOON-AI Terminal REPL (default)
- ``python -m moon terminal``         -> MOON-AI Terminal REPL (explicit)
- ``python -m moon run <task>``       -> CLI single-task runner
- ``python -m moon models``           -> pre-pull per-agent models
- ``python -m moon doctor|status|...``-> CLI subcommands

The real CLI lives in ``main.py`` (the ``moon`` / ``moon-terminal`` console
scripts point at ``main:main``).  This module used to re-implement the parser
and dispatch, which drifted from ``main.py`` (e.g. ``integrations`` / ``work``
were missing, and a few flags diverged).  It now delegates to the single source
of truth so every documented entry point behaves identically:

    python -m moon  ==  moon  ==  python main.py  ==  python -m moon_terminal
"""

from __future__ import annotations

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
import app.config.env_guard  # noqa: F401,E402


def main(argv=None) -> int:
    """Run the canonical MOON-AI CLI from ``main.py``.

    ``argv`` is optional for tests/programmatic use; when omitted the real
    process arguments are used (exactly like the console script).
    """
    # Imported lazily so the env guard above always runs first.
    from main import main as _canonical_main  # noqa: PLC0415

    if argv is None:
        return _canonical_main()

    old_argv = sys.argv
    sys.argv = [old_argv[0] if old_argv else "moon", *list(argv)]
    try:
        return _canonical_main()
    finally:
        sys.argv = old_argv


def _main() -> None:
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        sys.stderr.write("\nMOON-AI interrupted by user.\n")
        raise SystemExit(130)


if __name__ == "__main__":
    _main()
