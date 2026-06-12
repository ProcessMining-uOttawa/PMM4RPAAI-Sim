"""Parameter declarations and Scenario containers."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Literal


class ScenarioParams:
    """Base class for pattern-specific simulation parameters derived from a Scenario.

    Each Transformation subclass has a paired ScenarioParams subclass that
    holds the typed, validated inputs its apply_params() needs.
    """


@dataclass
class Parameter:
    """A single experiment factor with 3 levels (Taguchi-style)."""
    id: str
    label: str
    levels: list[Any]                          # exactly 3 values for L9/L18/L27
    kind: Literal["percentage", "duration_s", "cost", "categorical"] = "percentage"
    frozen: bool = False                       # if True, excluded from OA; levels[0] used in all scenarios


@dataclass
class Scenario:
    """One row of a Taguchi design: a concrete value per parameter."""
    id: str                                    # e.g. "S07"
    values: dict[str, Any]                     # {param_id: chosen_level}
    transformation_id: str
    target_activity: str
