"""Tests for core/taguchi.py — pick_array and build_scenarios."""

from __future__ import annotations
import pytest

from core.taguchi import build_scenarios, pick_array
from core.parameters import Parameter

# Standard Taguchi orthogonal arrays for 3-level factors (0-indexed levels).
# L9 (3^4): up to 4 factors.
L9 = [
    [0, 0, 0, 0],
    [0, 1, 1, 1],
    [0, 2, 2, 2],
    [1, 0, 1, 2],
    [1, 1, 2, 0],
    [1, 2, 0, 1],
    [2, 0, 2, 1],
    [2, 1, 0, 2],
    [2, 2, 1, 0],
]
# L18 (2^1 x 3^7): use only the seven 3-level columns (drop col 0 here).
L18 = [
    [0, 0, 0, 0, 0, 0, 0],
    [0, 1, 1, 1, 1, 1, 1],
    [0, 2, 2, 2, 2, 2, 2],
    [1, 0, 0, 1, 1, 2, 2],
    [1, 1, 1, 2, 2, 0, 0],
    [1, 2, 2, 0, 0, 1, 1],
    [2, 0, 1, 0, 2, 1, 2],
    [2, 1, 2, 1, 0, 2, 0],
    [2, 2, 0, 2, 1, 0, 1],
    [0, 0, 2, 2, 1, 1, 0],
    [0, 1, 0, 0, 2, 2, 1],
    [0, 2, 1, 1, 0, 0, 2],
    [1, 0, 1, 2, 0, 2, 1],
    [1, 1, 2, 0, 1, 0, 2],
    [1, 2, 0, 1, 2, 1, 0],
    [2, 0, 2, 1, 2, 0, 1],
    [2, 1, 0, 2, 0, 1, 2],
    [2, 2, 1, 0, 1, 2, 0],
]
# ── pick_array ────────────────────────────────────────────────────────────────


class TestPickArray:
    def test_negative_factor_raises(self):
        with pytest.raises(ValueError):
            pick_array(-1)

    def test_zero_factors_gives_l1(self):
        arr_label, arr, cols = pick_array(0)
        assert arr_label == "L1"
        assert arr == [[]]
        assert cols == 0

    def test_one_factor_gives_l9(self):
        arr_label, arr, cols = pick_array(1)

        assert arr_label == "L9"
        assert arr == L9
        assert cols == len(arr[0])

    def test_four_factors_gives_l9(self):
        arr_label, arr, cols = pick_array(4)

        assert arr_label == "L9"
        assert arr == L9
        assert cols == len(arr[0])

    def test_five_factors_gives_l18(self):
        arr_label, arr, cols = pick_array(5)

        assert arr_label == "L18"
        assert arr == L18
        assert cols == len(arr[0])

    def test_seven_factors_gives_l18(self):
        arr_label, arr, cols = pick_array(7)

        assert arr_label == "L18"
        assert arr == L18
        assert cols == len(arr[0])

    def test_eight_factors_raises(self):
        # No L27: the single pattern tops out at 7 factors, so 8+ has no OA.
        with pytest.raises(ValueError):
            pick_array(8)


# ── build_scenarios ───────────────────────────────────────────────────────────


class TestBuildScenarios:
    def _params(self, n: int) -> list[Parameter]:
        return [Parameter(f"p{i}", f"P{i}", [10, 20, 30]) for i in range(n)]

    def test_three_active_factors_gives_l9_nine_scenarios(self):
        name, scenarios = build_scenarios(
            self._params(3), "xor_split_automation", "Check credit"
        )
        assert name == "L9" and len(scenarios) == 9

    def test_six_active_factors_gives_l18_eighteen_scenarios(self):
        name, scenarios = build_scenarios(
            self._params(6), "xor_split_automation", "Check credit"
        )
        assert name == "L18" and len(scenarios) == 18

    def test_seven_active_factors_gives_l18_eighteen_scenarios(self):
        # The real pattern's factor count (7) — the largest supported design.
        name, scenarios = build_scenarios(
            self._params(7), "xor_split_automation", "Check credit"
        )
        assert name == "L18" and len(scenarios) == 18

    def test_frozen_factor_constant_across_all_scenarios(self):
        params = [
            Parameter("active", "Active", [10, 20, 30]),
            Parameter("frozen", "Frozen", [99, 99, 99], frozen=True),
        ]
        _, scenarios = build_scenarios(params, "xor_split_automation", "Check credit")
        assert all(s.values["frozen"] == 99 for s in scenarios)

    def test_active_factor_varies_across_scenarios(self):
        _, scenarios = build_scenarios(
            self._params(1), "xor_split_automation", "Check credit"
        )
        assert len({s.values["p0"] for s in scenarios}) == 3

    def test_all_levels_present_in_l9_column(self):
        _, scenarios = build_scenarios(
            self._params(1), "xor_split_automation", "Check credit"
        )
        assert {s.values["p0"] for s in scenarios} == {10, 20, 30}

    def test_all_frozen_gives_single_l1_scenario(self):
        params = [Parameter("p", "P", [5, 5, 5], frozen=True)]
        name, scenarios = build_scenarios(
            params, "xor_split_automation", "Check credit"
        )
        assert name == "L1" and len(scenarios) == 1 and scenarios[0].id == "S01"

    def test_scenario_ids_are_zero_padded(self):
        _, scenarios = build_scenarios(
            self._params(2), "xor_split_automation", "Check credit"
        )
        assert scenarios[0].id == "S01"
        assert scenarios[8].id == "S09"
