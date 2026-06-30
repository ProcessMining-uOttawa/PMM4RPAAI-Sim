"""st.number_input config for the factor-levels panel, keyed on Parameter.kind."""

from __future__ import annotations

from typing import Any

from core.parameters import ParameterKind


def number_input_kwargs(kind: ParameterKind, value: float) -> dict[str, Any]:
    """Map a Parameter.kind to the st.number_input kwargs for one factor level."""
    if kind == "percentage":
        return {
            "value": float(value),
            "min_value": 0.0,
            "max_value": 100.0,
            "step": 1.0,
            "format": "%.0f",
        }
    if kind == "duration_s":
        return {"value": float(value), "min_value": 0.0, "step": 1.0, "format": "%.1f"}
    if kind == "categorical":
        return {"value": int(value), "min_value": 1, "step": 1}
    if kind == "cost":
        return {"value": float(value), "min_value": 0.0, "step": 0.01, "format": "%.2f"}
    return {"value": float(value)}
