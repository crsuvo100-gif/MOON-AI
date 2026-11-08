"""Task Analyzer (spec sections 10, 6: orchestrator/task_analyzer.py).

Re-exports the real TaskAnalyzer/GoalSpec from app.runtime.task_analyzer.
"""

from app.runtime.task_analyzer import GoalSpec, TaskAnalyzer

__all__ = ["GoalSpec", "TaskAnalyzer"]
