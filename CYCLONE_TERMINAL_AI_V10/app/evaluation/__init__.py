"""MOON-AI Evaluation package (spec section 6: evaluation/, section 28).

Compatibility layer re-exporting the real EvaluationEngine from app.runtime.evaluation.
Non-destructive.
"""

from app.runtime.evaluation import EvaluationEngine, ScoreCard

__all__ = ["EvaluationEngine", "ScoreCard"]
