"""Parameter declarations and Scenario containers."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Literal


@dataclass
class Parameter:
    """A single experiment factor with 3 levels (Taguchi-style)."""
    id: str
    label: str
    levels: list[Any]                          # exactly 3 values for L9/L18/L27
    kind: Literal["percentage", "duration_s", "cost", "categorical"] = "percentage"


@dataclass
class Scenario:
    """One row of a Taguchi design: a concrete value per parameter."""
    id: str                                    # e.g. "S07"
    values: dict[str, Any]                     # {param_id: chosen_level}
    transformation_id: str
    target_activity: str


@dataclass(frozen=True)
class AutomationScenario:
    """Human-readable inputs for one automation simulation run.

    Primary fields are set directly. Complements are computed properties so
    the caller never has to manage them explicitly.
    """
    automation_rate:       float  # [0, 1] fraction of cases routed to the bot
    bot_failure_rate:      float  # [0, 1] fraction of bot attempts that fail
    bot_execution_time:    float  # mean bot task duration (seconds)
    manual_execution_time: float  # mean human task duration (seconds)
    num_bots:              int    # bot resource pool size
    num_manual_resources:  int    # human resource pool size

    def __post_init__(self) -> None:
        for name, val in (("automation_rate",  self.automation_rate),
                          ("bot_failure_rate", self.bot_failure_rate)):
            if not 0.0 <= val <= 1.0:
                raise ValueError(f"{name} must be in [0, 1], got {val}")
        for name, val in (("num_bots", self.num_bots),
                          ("num_manual_resources", self.num_manual_resources)):
            if val < 1:
                raise ValueError(f"{name} must be ≥ 1, got {val}")

    @property
    def manual_branch_rate(self) -> float:
        return round(1.0 - self.automation_rate, 10)

    @property
    def bot_success_rate(self) -> float:
        return round(1.0 - self.bot_failure_rate, 10)

    @classmethod
    def from_taguchi_values(cls, values: dict) -> "AutomationScenario":
        """Bridge: construct from a Taguchi-generated values dict."""
        def _v(suffix: str, default: float) -> float:
            for k, v in values.items():
                if k.endswith("." + suffix):
                    return float(v)
            return default

        return cls(
            automation_rate=_v("pct_auto", 50.0) / 100.0,
            bot_failure_rate=1.0 - _v("pct_ok", 90.0) / 100.0,
            bot_execution_time=_v("t_auto", 60.0),
            manual_execution_time=_v("t_manual", 1800.0),
            num_bots=int(_v("num_bots", 1.0)),
            num_manual_resources=int(_v("num_manual_resources", 1.0)),
        )
