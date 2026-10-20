"""MOON-AI top-level package marker.

MOON-AI is a single-package project: all functionality lives in
``app`` (app/brain, app/agents, app/orchestrator, app/terminal, ...).
``moon`` itself is only a delegation surface for documented entry points:

- ``python -m MOON-AI``        -> launch the MOON-AI Terminal REPL (default)
- ``python -m MOON-AI terminal`` -> explicit terminal REPL
- ``python -m MOON-AI <cmd>``  -> CLI subcommands (run, models, doctor, ...)

Actual implementation and all business logic reside in ``app``. Adding a
top-level ``moon`` package keeps the documented ``python -m MOON-AI`` /
``python -m MOON-AI terminal`` conventions working without modifying
``main.py`` or the installed entry points.
"""
