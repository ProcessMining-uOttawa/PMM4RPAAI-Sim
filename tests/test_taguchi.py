"""Tests for core/taguchi.py — pick_array and build_scenarios."""

from __future__ import annotations
from collections import Counter

import pytest

from core.taguchi import build_scenarios, pick_array, L9 as PROD_L9, L18 as PROD_L18
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
        # No L27: L18's seven 3-level columns are the ceiling, so 8+ has no OA.
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
        # The real pattern's factor count (6; 5 with a frozen manual pool).
        name, scenarios = build_scenarios(
            self._params(6), "xor_split_automation", "Check credit"
        )
        assert name == "L18" and len(scenarios) == 18

    def test_seven_active_factors_gives_l18_eighteen_scenarios(self):
        # L18's full column capacity — the largest supported design.
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

    def test_column_to_factor_mapping(self):
        # Each factor must read ITS OWN L9 column, not column 0 for every factor.
        # Rows 3 and 6 (0-indexed) have differing columns 0 and 1, so a
        # row[0]-for-all-factors mutant (which would set p1 = p0's level) is
        # caught here — the two params share a level list, so only the distinct
        # column indices distinguish correct from mutant.
        _, scenarios = build_scenarios(
            self._params(2), "xor_split_automation", "Check credit"
        )
        # L9 row [1, 0, 1, 2] → p0 = levels[1] = 20, p1 = levels[0] = 10
        assert scenarios[3].values == {"p0": 20, "p1": 10}
        # L9 row [2, 0, 2, 1] → p0 = levels[2] = 30, p1 = levels[0] = 10
        assert scenarios[6].values == {"p0": 30, "p1": 10}


# ── Orthogonality properties ────────────────────────────────────────────────────


class TestOrthogonality:
    """Self-verifying OA properties for the PRODUCTION L9/L18 arrays.

    TestPickArray pins the arrays only against copies of themselves (the exact
    shape of the historical L18 corruption, where columns were cyclically
    permuted yet still equal to an equally-corrupt pin). These property tests
    verify the mathematical definition of a strength-2 orthogonal array directly,
    so a future permutation/typo fails here regardless of any pinned copy.
    """

    @pytest.mark.parametrize("array", [PROD_L9, PROD_L18])
    def test_columns_are_balanced(self, array):
        # Each level 0/1/2 appears N/3 times in every column.
        n_rows = len(array)
        for col in range(len(array[0])):
            counts = Counter(row[col] for row in array)
            assert set(counts) == {0, 1, 2}
            assert all(count == n_rows // 3 for count in counts.values())

    @pytest.mark.parametrize("array", [PROD_L9, PROD_L18])
    def test_strength_two_orthogonal(self, array):
        # Every ordered pair of distinct columns contains each of the 9 ordered
        # level-pairs exactly N/9 times (L9: 1×, L18: 2×).
        n_rows = len(array)
        n_cols = len(array[0])
        expected = n_rows // 9
        all_pairs = {(a, b) for a in (0, 1, 2) for b in (0, 1, 2)}
        for c1 in range(n_cols):
            for c2 in range(n_cols):
                if c1 == c2:
                    continue
                counts = Counter((row[c1], row[c2]) for row in array)
                assert set(counts) == all_pairs
                assert all(count == expected for count in counts.values())

    @pytest.mark.parametrize("array", [PROD_L9, PROD_L18])
    def test_no_duplicate_rows(self, array):
        rows = [tuple(row) for row in array]
        assert len(set(rows)) == len(rows)
