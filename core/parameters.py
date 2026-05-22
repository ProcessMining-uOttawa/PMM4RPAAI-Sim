"""Parameter declarations and Scenario container."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Literal


@dataclass
class Parameter:
    """A single experiment factor with 3 levels (Taguchi-style)."""
    id: str
    label: str
    levels: list[Any]                          # exactly 3 values for L9/L18/L27
    kind: Literal["percentage", "duration_s", "cost", "categorical"] = "percentage"
    # How the value is written into the Prosimos JSON.
    # Either a JSONPath-like list of keys, or a callable (json, value) -> None.
    inject: list[str] | Callable[[dict, Any], None] = field(default_factory=list)


@dataclass
class Scenario:
    """One row of a Taguchi design: a concrete value per parameter."""
    id: str                                    # e.g. "S07"
    values: dict[str, Any]                     # {param_id: chosen_level}
    transformation_id: str
    target_activity: str
