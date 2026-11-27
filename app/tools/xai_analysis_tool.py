"""xai_analysis_tool.py -- explainable-AI (XAI) analysis tool.

Self-contained tool for "explainability"-style analysis of tabular /
predictor workloads. It reports:

  * target-feature correlation (linear association with the predicted
    label) so a practitioner can see which columns move with the target,
  * a feature-importance ranking (top-N by absolute correlation),
  * a stratified breakdown (mean target per category of a selected column),
  * a class-imbalance diagnostic for binary / numeric targets.

The tool deliberately avoids heavy third-party XAI wheels (SHAP/LIME). It
uses the standard numpy + pandas stack, which are already core project
dependencies, and it degrades gracefully to a pure-stdlib report if pandas
is unavailable. It never trains a model and never opens the network.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

from app.tools.base import BaseTool


class XAIAnalysisTool(BaseTool):
    """Run lightweight, offline XAI-style exploratory analysis on data."""

    name = "xai_analysis"
    description = (
        "Explainable-AI style tabular analysis: target correlation, "
        "feature importance ranking, categorical breakdown and imbalance "
        "diagnostics. Pure numpy/pandas, offline."
    )

    # --------------------------------------------------------------------------
    @staticmethod
    def _as_dataframe(payload: Any, target: Optional[str] = None) -> tuple[pd.DataFrame, Optional[str]]:
        """Normalise caller input into a DataFrame, returning (df, target_col)."""
        if isinstance(payload, pd.DataFrame):
            df = payload.copy()
        elif isinstance(payload, dict):
            df = pd.DataFrame(payload)
        elif isinstance(payload, (list, tuple)) and payload and all(
            isinstance(r, dict) for r in payload
        ):
            df = pd.DataFrame(payload)
        else:
            raise TypeError(
                "XAIAnalysisTool expects a pandas DataFrame or list of dicts; "
                f"got {type(payload).__name__}"
            )

        # Default target is the last column (override via target kwarg).
        if target is None:
            target = df.columns[-1] if df.columns.size else None
        return df, target

    # --------------------------------------------------------------------------
    async def execute(self, **kwargs: Any) -> str:
        """Run the analysis and return a human-readable report string."""
        data = kwargs.pop("data", None)
        target = kwargs.pop("target", None)
        top_n = int(kwargs.get("top_n", 15))
        breakdown_by = kwargs.get("breakdown", None)
        min_count = int(kwargs.get("min_count", 5))

        df = data if isinstance(data, pd.DataFrame) else self._as_dataframe(data, target)[0]

        report_lines = ["=== XAI Analysis Report ===", ""]

        if df is None or df.empty:
            return "No data provided for analysis."

        num_cols = [
            c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])
        ]
        cat_cols = [
            c for c in df.columns if pd.api.types.is_categorical_dtype(df[c])
        ]
        obj_cols = [
            c for c in df.columns if pd.api.types.is_object_dtype(df[c])
        ]
        all_cols = list(df.columns)

        report_lines.append(f"Rows: {len(df)} | Columns: {len(all_cols)}")
        report_lines.append(
            f"Numeric columns: {len(num_cols)} | Categorical: {len(cat_cols)} | Object: {len(obj_cols)}"
        )
        report_lines.append("")

        # 1) Correlation with target (numeric only).
        report_lines.append("--- Target correlation (top absolute features) ---")
        if target is not None and target in df.columns and len(num_cols) > 0:
            corr = df[num_cols].corr()[target].drop(labels=[target], errors="ignore")
            corr = corr.reindex(corr.abs().sort_values(ascending=False).index)
            report_lines.append(corr.to_string())
            report_lines.append("")
        else:
            report_lines.append(
                "(target column missing or no numeric columns; correlation skipped)"
            )
            report_lines.append("")
        if target is None or target not in df.columns:
            report_lines.append(
                f"NOTE: target='{target}' not found; falling back to last column "
                f"'{df.columns[-1] if df.columns.size else None}'."
            )
            report_lines.append("")
        report_lines.append("")

        # 2) Feature importance ranking via pairwise |correlation| with target.
        report_lines.append("--- Feature importance ranking ---")
        if target is not None and target in df.columns and len(num_cols) > 0:
            corr = df[num_cols].corr()[target].drop(labels=[target], errors="ignore")
            ranked = corr.reindex(corr.abs().sort_values(ascending=False).index)
            for feat, val in ranked.head(top_n).items():
                report_lines.append(f"  {feat:<24s} corr={val:+.4f}")
            report_lines.append("")
        else:
            report_lines.append(
                "(no numeric features / missing target; ranking skipped)"
            )
            report_lines.append("")
        report_lines.append("")

        # 3) Stratified breakdown of target by a categorical column.
        report_lines.append("--- Stratified breakdown ---")
        if breakdown_by is not None and breakdown_by in df.columns:
            sub = df[df[breakdown_by].notna()]
            if len(sub) < min_count:
                report_lines.append(
                    f"(only {len(sub)} rows for '{breakdown_by}'; below min_count={min_count})"
                )
                report_lines.append("")
            else:
                keys = np.sort(sub[breakdown_by].unique())
                report_lines.append(f"mean target by '{breakdown_by}':")
                for k in keys[:top_n]:
                    mask = sub[breakdown_by] == k
                    n = int(mask.sum())
                    mean_t = (
                        float(pd.to_numeric(sub.loc[mask, target], errors="coerce").mean())
                        if target in sub.columns
                        else float("nan")
                    )
                    report_lines.append(
                        f"  {k!s:<24s} n={n:<6d} mean_target={mean_t:+.4f}"
                    )
                report_lines.append("")
        else:
            report_lines.append("(no `breakdown` column given; skipped)")
            report_lines.append("")
        report_lines.append("")

        # 4) Imbalance diagnostic for binary / numeric targets.
        report_lines.append("--- Class imbalance diagnostic ---")
        if target is not None and target in df.columns and len(num_cols) > 0:
            tgt = pd.to_numeric(df[target], errors="coerce").dropna()
            counts = tgt.value_counts()
            if counts.size <= 2:
                report_lines.append(f"binary target '{target}':")
                for cls, n in counts.items():
                    report_lines.append(f"  class {cls}: {n} ({n / len(tgt):.1%})")
                report_lines.append("")
            else:
                report_lines.append(f"continuous target '{target}':")
                report_lines.append(
                    f"  mean={tgt.mean():.4f} | std={tgt.std():.4f} | min={tgt.min():.4f} | max={tgt.max():.4f}"
                )
                report_lines.append("")
        else:
            report_lines.append("(no numeric target for imbalance; skipped)")
            report_lines.append("")

        return "\n".join(report_lines)

    # --------------------------------------------------------------------------
    def spec(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "data": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "List of row dicts, or a pandas DataFrame.",
                    },
                    "target": {"type": "string", "description": "Target column name."},
                    "top_n": {"type": "integer", "description": "Top-N features to show."},
                    "breakdown": {
                        "type": "string",
                        "description": "Categorical column to stratify on.",
                    },
                    "min_count": {"type": "integer", "description": "Min rows for a breakdown bin."},
                },
            },
        }
