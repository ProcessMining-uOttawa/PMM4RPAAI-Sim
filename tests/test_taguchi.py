"""Tests for core/taguchi.py, AutomationParams.from_taguchi_values, and demo monotonicity."""
from __future__ import annotations
import pytest

from core.taguchi import build_scenarios, pick_array
from core.parameters import Parameter
from core.transformations import AutomationParams


# ── pick_array ────────────────────────────────────────────────────────────────

class TestPickArray:

    def test_one_factor_gives_l9(self):
        assert pick_array(1)[0] == "L9"

    def test_four_factors_gives_l9(self):
        assert pick_array(4)[0] == "L9"

    def test_five_factors_gives_l18(self):
        assert pick_array(5)[0] == "L18"

    def test_seven_factors_gives_l18(self):
        assert pick_array(7)[0] == "L18"

    def test_eight_factors_gives_l27(self):
        assert pick_array(8)[0] == "L27"

    def test_thirteen_factors_gives_l27(self):
        assert pick_array(13)[0] == "L27"

    def test_fourteen_factors_raises(self):
        with pytest.raises(ValueError):
            pick_array(14)


# ── build_scenarios ───────────────────────────────────────────────────────────

class TestBuildScenarios:

    def _params(self, n: int) -> list[Parameter]:
        return [Parameter(f"p{i}", f"P{i}", [10, 20, 30]) for i in range(n)]

    def test_three_active_factors_gives_l9_nine_scenarios(self):
        name, scenarios = build_scenarios(self._params(3), "t", "Act")
        assert name == "L9" and len(scenarios) == 9

    def test_six_active_factors_gives_l18_eighteen_scenarios(self):
        name, scenarios = build_scenarios(self._params(6), "t", "Act")
        assert name == "L18" and len(scenarios) == 18

    def test_eight_active_factors_gives_l27_twentyseven_scenarios(self):
        name, scenarios = build_scenarios(self._params(8), "t", "Act")
        assert name == "L27" and len(scenarios) == 27

    def test_frozen_factor_constant_across_all_scenarios(self):
        params = [
            Parameter("active", "Active", [10, 20, 30]),
            Parameter("frozen", "Frozen", [99, 99, 99], frozen=True),
        ]
        _, scenarios = build_scenarios(params, "t", "Act")
        assert all(s.values["frozen"] == 99 for s in scenarios)

    def test_active_factor_varies_across_scenarios(self):
        _, scenarios = build_scenarios(self._params(1), "t", "Act")
        assert len({s.values["p0"] for s in scenarios}) == 3

    def test_all_levels_present_in_l9_column(self):
        _, scenarios = build_scenarios(self._params(1), "t", "Act")
        assert {s.values["p0"] for s in scenarios} == {10, 20, 30}

    def test_all_frozen_gives_single_l1_scenario(self):
        params = [Parameter("p", "P", [5, 5, 5], frozen=True)]
        name, scenarios = build_scenarios(params, "t", "Act")
        assert name == "L1" and len(scenarios) == 1 and scenarios[0].id == "S01"

    def test_scenario_ids_are_zero_padded(self):
        _, scenarios = build_scenarios(self._params(2), "t", "Act")
        assert scenarios[0].id == "S01"
        assert scenarios[8].id == "S09"


# ── AutomationParams.from_taguchi_values ────────────────────────────────────

class TestFromTaguchiValues:

    _FULL = {
        "pct_auto":            75.0,
        "pct_ok":              90.0,
        "t_auto":              60.0,
        "t_manual":          1800.0,
        "num_bots":               2,
        "num_manual_resources":   3,
        "num_cases":            500,
    }

    def test_full_values_mapped_correctly(self):
        s = AutomationParams.from_taguchi_values(self._FULL)
        assert s.automation_rate       == pytest.approx(0.75)
        assert s.bot_failure_rate      == pytest.approx(0.10)  # 1 - 90/100
        assert s.bot_execution_time    == pytest.approx(60.0)
        assert s.manual_execution_time == pytest.approx(1800.0)
        assert s.num_bots              == 2
        assert s.num_manual_resources  == 3
        assert s.num_cases             == 500

    def test_empty_dict_uses_defaults(self):
        s = AutomationParams.from_taguchi_values({})
        assert s.automation_rate      == pytest.approx(0.50)
        assert s.bot_failure_rate     == pytest.approx(0.10)
        assert s.num_bots             == 1
        assert s.num_manual_resources == 1
        assert s.num_cases            == 100

    def test_num_bots_and_num_manual_keys_used(self):
        s = AutomationParams.from_taguchi_values(
            {"num_bots": 3, "num_manual_resources": 5}
        )
        assert s.num_bots == 3
        assert s.num_manual_resources == 5

    def test_selected_resource_id_passed_through(self):
        s = AutomationParams.from_taguchi_values({}, selected_resource_id="res_42")
        assert s.selected_resource_id == "res_42"


# ── Demo monotonicity ─────────────────────────────────────────────────────────

class TestDemoMonotonicity:

    def test_larger_resource_pool_reduces_cycle_time(self):
        from core.demo import _fake_simulate as fake_simulate
        from core.parameters import Scenario

        def _mean_cycle(num_bots: int, num_man: int, n_reps: int = 20) -> float:
            s = Scenario(
                "S01",
                {
                    "pct_auto": 50, "pct_ok": 90,
                    "t_auto": 30, "t_manual": 300,
                    "num_bots": num_bots, "num_manual_resources": num_man,
                    "num_cases": 500,
                },
                "t_id", "Act",
            )
            return sum(fake_simulate(s, r).mean_cycle_h for r in range(n_reps)) / n_reps

        assert _mean_cycle(3, 3) < _mean_cycle(1, 1)
