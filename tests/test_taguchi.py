"""Tests for core/taguchi.py — pick_array and build_scenarios."""

from __future__ import annotations
import pytest

from core.taguchi import build_scenarios, pick_array
from core.parameters import Parameter


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
