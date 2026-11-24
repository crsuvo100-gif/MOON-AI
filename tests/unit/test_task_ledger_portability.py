"""Regression tests: task ledger must resolve its project root portably.

Guards against reintroducing a machine-specific hard-coded path such as
``/home/meow/Projects/MOON`` in core code (README promises portability).
"""

from __future__ import annotations

import os
from pathlib import Path

from app.memory import task_ledger


def test_project_root_is_not_hardcoded(monkeypatch):
    """Detection uses env override and source-tree layout, never a fixed path."""
    monkeypatch.setenv("MOON_PROJECT_ROOT", "/tmp/moon-portable-root")
    detected = task_ledger._detect_project_root()
    assert detected == Path("/tmp/moon-portable-root")


def test_project_root_from_source_tree(monkeypatch):
    """Without an override, the root is derived from this package's location."""
    monkeypatch.delenv("MOON_PROJECT_ROOT", raising=False)
    detected = task_ledger._detect_project_root()
    # Must be the directory that contains app/memory, not a literal user home.
    assert (detected / "app" / "memory").is_dir()
    assert str(detected) != "/home/meow/Projects/MOON" or Path(
        "/home/meow/Projects/MOON/app/memory"
    ).is_dir()


def test_get_ledger_is_cached(monkeypatch):
    """Repeated default calls must return the same ledger instance."""
    monkeypatch.delenv("MOON_PROJECT_ROOT", raising=False)
    task_ledger._default_ledger = None
    first = task_ledger.get_ledger()
    second = task_ledger.get_ledger()
    assert first is second
