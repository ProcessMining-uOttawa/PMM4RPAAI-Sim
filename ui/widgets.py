"""Streamlit widget helpers for the factor-levels panel."""
from __future__ import annotations


def level_input_kwargs(kind: str, value) -> dict:
    """Map Parameter.kind to st.number_input constraints."""
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
