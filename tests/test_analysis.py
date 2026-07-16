"""Tests for core/analysis.py — no external tools required."""

from __future__ import annotations
import math

import pandas as pd
import pytest

from core.analysis import (
    aggregate,
    compare_to_baseline,
    main_effects,
    signal_to_noise,
    sn_ranking,
    sn_export_table,
    rank,
)
from core.goals import Goal
from core.metrics import MetricDirection, MetricRegistry
from core.parameters import Parameter
from core.constants import (
    COL_MEAN_CYCLE_H,
    COL_MEDIAN_CYCLE_H,
    COL_MEAN_COST,
    COL_MEAN_CYCLE_H_MEAN,
    COL_MEDIAN_CYCLE_H_MEAN,
    COL_MEAN_COST_MEAN,
    COL_TOTAL_CYCLE_S,
    COL_TOTAL_COST,
    COL_TOTAL_CYCLE_S_MEAN,
    COL_TOTAL_COST_MEAN,
    COL_TOTAL_REWORK_COUNT,
    COL_REWORK_RATE,
    COL_TOTAL_REWORK_COUNT_MEAN,
    COL_REWORK_RATE_MEAN,
    COL_TOTAL_BOT_FAILURE_COUNT,
    COL_TOTAL_BOT_FAILURE_COUNT_MEAN,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _results_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "scenario_id": "S01",
                "replication": 0,
                COL_MEAN_CYCLE_H: 10.0,
                COL_MEDIAN_CYCLE_H: 9.0,
                COL_MEAN_COST: 5.0,
                "f_a": "low",
                COL_TOTAL_CYCLE_S: 36000.0,
                COL_TOTAL_COST: 500.0,
                COL_TOTAL_REWORK_COUNT: 2.0,
                COL_REWORK_RATE: 10.0,
                COL_TOTAL_BOT_FAILURE_COUNT: 1.0,
            },
            {
                "scenario_id": "S01",
                "replication": 1,
                COL_MEAN_CYCLE_H: 12.0,
                COL_MEDIAN_CYCLE_H: 11.0,
                COL_MEAN_COST: 7.0,
                "f_a": "low",
                COL_TOTAL_CYCLE_S: 43200.0,
                COL_TOTAL_COST: 700.0,
                COL_TOTAL_REWORK_COUNT: 4.0,
                COL_REWORK_RATE: 20.0,
                COL_TOTAL_BOT_FAILURE_COUNT: 3.0,
            },
            {
                "scenario_id": "S02",
                "replication": 0,
                COL_MEAN_CYCLE_H: 20.0,
                COL_MEDIAN_CYCLE_H: 18.0,
                COL_MEAN_COST: 10.0,
                "f_a": "high",
                COL_TOTAL_CYCLE_S: 72000.0,
                COL_TOTAL_COST: 1000.0,
                COL_TOTAL_REWORK_COUNT: 0.0,
                COL_REWORK_RATE: 0.0,
                COL_TOTAL_BOT_FAILURE_COUNT: 0.0,
            },
            {
                "scenario_id": "S02",
                "replication": 1,
                COL_MEAN_CYCLE_H: 22.0,
                COL_MEDIAN_CYCLE_H: 20.0,
                COL_MEAN_COST: 12.0,
                "f_a": "high",
                COL_TOTAL_CYCLE_S: 79200.0,
                COL_TOTAL_COST: 1200.0,
                COL_TOTAL_REWORK_COUNT: 2.0,
                COL_REWORK_RATE: 10.0,
                COL_TOTAL_BOT_FAILURE_COUNT: 2.0,
            },
        ]
    )


# ── signal_to_noise ───────────────────────────────────────────────────────────


class TestSignalToNoise:
    def test_smaller_is_better(self):
        vals = [2.0, 4.0, 4.0]
        expected = -10 * math.log10(sum(v * v for v in vals) / len(vals))
        assert signal_to_noise(vals) == pytest.approx(expected)

    def test_larger_is_better(self):
        vals = [2.0, 4.0]
        expected = -10 * math.log10(sum(1 / (v * v) for v in vals) / len(vals))
        assert signal_to_noise(
            vals, direction=MetricDirection.LARGER_IS_BETTER
        ) == pytest.approx(expected)

    def test_empty_returns_nan(self):
        assert math.isnan(signal_to_noise([]))

    def test_all_none_returns_nan(self):
        assert math.isnan(signal_to_noise([None, None]))

    def test_zeros_return_nan_without_floor(self):
        assert math.isnan(signal_to_noise([0.0, 0.0]))

    def test_floor_prevents_nan_for_zeros(self):
        result = signal_to_noise([0.0, 0.0], floor=0.01)
        assert not math.isnan(result)
        expected = -10 * math.log10(sum(v * v for v in [0.01, 0.01]) / 2)
        assert result == pytest.approx(expected)

    def test_floor_applied_to_nonzero_values(self):
        result = signal_to_noise([2.0, 4.0], floor=0.01)
        expected = -10 * math.log10(sum(v * v for v in [2.01, 4.01]) / 2)
        assert result == pytest.approx(expected)

    def test_none_values_ignored(self):
        assert signal_to_noise([None, 2.0, None, 4.0]) == pytest.approx(
            signal_to_noise([2.0, 4.0])
        )

    def test_invalid_direction_raises(self):
        with pytest.raises(ValueError):
            signal_to_noise([1.0], direction="invalid")  # type: ignore[arg-type]


# ── aggregate ─────────────────────────────────────────────────────────────────


class TestAggregate:
    def test_one_row_per_scenario(self):
        # Two scenarios in → two rows out. Also guards _NON_FACTOR_COLS excluding
        # median: were median grouped as a factor, aggregate() would fragment the
        # groups and this count would exceed 2.
        assert len(aggregate(_results_df())) == 2

    def test_means_correct(self):
        agg = aggregate(_results_df())
        row = agg[agg["scenario_id"] == "S01"].iloc[0]
        assert row[COL_MEAN_CYCLE_H_MEAN] == pytest.approx(11.0)
        assert row[COL_MEAN_COST_MEAN] == pytest.approx(6.0)

    def test_median_mean_correct(self):
        agg = aggregate(_results_df())
        row = agg[agg["scenario_id"] == "S01"].iloc[0]
        # S01 medians 9.0, 11.0 → mean 10.0, distinct from the mean-cycle mean
        # of 11.0 (confirms median is aggregated as its own column).
        assert row[COL_MEDIAN_CYCLE_H_MEAN] == pytest.approx(10.0)

    def test_rework_means_correct(self):
        agg = aggregate(_results_df())
        row = agg[agg["scenario_id"] == "S01"].iloc[0]
        assert row[COL_TOTAL_REWORK_COUNT_MEAN] == pytest.approx(3.0)  # (2 + 4) / 2
        assert row[COL_REWORK_RATE_MEAN] == pytest.approx(15.0)  # (10.0 + 20.0) / 2

    def test_bot_failure_mean_correct(self):
        agg = aggregate(_results_df())
        row = agg[agg["scenario_id"] == "S01"].iloc[0]
        assert row[COL_TOTAL_BOT_FAILURE_COUNT_MEAN] == pytest.approx(2.0)  # (1+3)/2

    def test_nan_cost_propagates(self):
        df = pd.DataFrame(
            [
                {
                    "scenario_id": "S01",
                    "replication": 0,
                    "f_a": "low",
                    COL_MEAN_CYCLE_H: 10.0,
                    COL_MEDIAN_CYCLE_H: 9.0,
                    COL_MEAN_COST: float("nan"),
                    COL_TOTAL_CYCLE_S: 36000.0,
                    COL_TOTAL_COST: 500.0,
                    COL_TOTAL_REWORK_COUNT: 2.0,
                    COL_REWORK_RATE: 5.0,
                    COL_TOTAL_BOT_FAILURE_COUNT: 1.0,
                }
            ]
        )
        agg = aggregate(df)
        assert math.isnan(agg[COL_MEAN_COST_MEAN].iloc[0])


# ── compare_to_baseline ───────────────────────────────────────────────────────


class TestCompareToBaseline:
    def _agg(self):
        return pd.DataFrame(
            [
                {
                    "scenario_id": "S01",
                    COL_TOTAL_CYCLE_S_MEAN: 7200.0,
                    COL_TOTAL_COST_MEAN: 200.0,
                    COL_TOTAL_REWORK_COUNT_MEAN: 5.0,
                    COL_REWORK_RATE_MEAN: 10.0,
                    COL_TOTAL_BOT_FAILURE_COUNT_MEAN: 6.0,
                },
                {
                    "scenario_id": "S02",
                    COL_TOTAL_CYCLE_S_MEAN: 3600.0,
                    COL_TOTAL_COST_MEAN: 80.0,
                    COL_TOTAL_REWORK_COUNT_MEAN: 2.0,
                    COL_REWORK_RATE_MEAN: 4.0,
                    COL_TOTAL_BOT_FAILURE_COUNT_MEAN: 3.0,
                },
            ]
        )

    def _baseline(self):
        return {
            COL_TOTAL_CYCLE_S_MEAN: 3600.0,
            COL_TOTAL_COST_MEAN: 100.0,
            COL_TOTAL_REWORK_COUNT_MEAN: 4.0,
            COL_REWORK_RATE_MEAN: 8.0,
            COL_TOTAL_BOT_FAILURE_COUNT_MEAN: 0.0,  # structurally 0 at 0% auto
        }

    def test_baseline_row_is_first(self):
        df = compare_to_baseline(self._agg(), self._baseline())
        assert df.iloc[0]["Scenario"] == "Baseline"

    def test_row_count(self):
        df = compare_to_baseline(self._agg(), self._baseline())
        assert len(df) == 3  # baseline + 2 scenarios

    def test_baseline_deltas_are_zero(self):
        df = compare_to_baseline(self._agg(), self._baseline())
        assert df.iloc[0]["Δ Time (h)"] == 0.0
        assert df.iloc[0]["Δ Cost ($)"] == 0.0

    def test_delta_values(self):
        df = compare_to_baseline(self._agg(), self._baseline())
        s02 = df[df["Scenario"] == "S02"].iloc[0]
        assert s02["Total Cycle Time (h)"] == pytest.approx(1.0)
        assert s02["Δ Time (h)"] == pytest.approx(0.0)
        assert s02["Δ Cost ($)"] == pytest.approx(-20.0)
        assert s02["Δ Cost (%)"] == pytest.approx(-20.0)
        # S01 has a NON-zero cycle-time delta, so it pins the seconds→hours
        # display_fn on the delta itself: 7200/3600 − 3600/3600 = 2.0 − 1.0 = 1.0 h.
        # A raw-seconds delta would give 3600.0.
        s01 = df[df["Scenario"] == "S01"].iloc[0]
        assert s01["Δ Time (h)"] == pytest.approx(1.0)
        assert s01["Δ Time (%)"] == pytest.approx(100.0)

    def test_zero_baseline_cost_gives_nan_pct(self):
        # _pct_delta returns NaN when the baseline value is 0 (documented as a
        # blank cell). S01 cost is 200 vs a zero baseline → percent is undefined.
        baseline = {**self._baseline(), COL_TOTAL_COST_MEAN: 0.0}
        df = compare_to_baseline(self._agg(), baseline)
        s01 = df[df["Scenario"] == "S01"].iloc[0]
        assert math.isnan(s01["Δ Cost (%)"])

    def test_baseline_rework_deltas_are_zero(self):
        df = compare_to_baseline(self._agg(), self._baseline())
        baseline = df.iloc[0]
        assert baseline["Δ Rework Count"] == 0.0
        assert baseline["Δ Rate (pp)"] == 0.0

    def test_rework_delta_values(self):
        df = compare_to_baseline(self._agg(), self._baseline())
        s02 = df[df["Scenario"] == "S02"].iloc[0]
        assert s02["Rework Count"] == pytest.approx(2.0)
        assert s02["Δ Rework Count"] == pytest.approx(-2.0)
        assert s02["Δ Rework (%)"] == pytest.approx(-50.0)
        assert s02["Rework Rate (%)"] == pytest.approx(4.0)
        assert s02["Δ Rate (pp)"] == pytest.approx(-4.0)

    def test_bot_failure_columns(self):
        df = compare_to_baseline(self._agg(), self._baseline())
        baseline = df.iloc[0]
        s02 = df[df["Scenario"] == "S02"].iloc[0]
        assert baseline["Bot Failures"] == 0.0
        assert baseline["Δ Bot Failures"] == 0.0
        # Zero baseline → the delta IS the scenario's own count.
        assert s02["Bot Failures"] == pytest.approx(3.0)
        assert s02["Δ Bot Failures"] == pytest.approx(3.0)
        # No percent-change column: pct vs a structurally-zero baseline is undefined.
        assert not any("Bot Failures (%)" in c for c in df.columns)

    def test_single_baseline_row_and_no_cases_column(self):
        # One uniform case count → exactly one baseline row precedes all scenarios.
        df = compare_to_baseline(self._agg(), self._baseline())
        baseline_rows = df[df["Scenario"] == "Baseline"]
        assert len(baseline_rows) == 1
        assert "Cases" not in df.columns  # one uniform case count → no per-row Cases


# ── main_effects ──────────────────────────────────────────────────────────────


class TestMainEffects:
    def test_has_required_columns(self):
        me = main_effects(_results_df(), MetricRegistry.CYCLE_TIME)
        assert {"factor", "level", "mean", "sn"} <= set(me.columns)

    def test_correct_factors_and_levels(self):
        me = main_effects(_results_df(), MetricRegistry.CYCLE_TIME)
        assert set(me["factor"].unique()) == {"f_a"}
        assert set(me["level"].unique()) == {"low", "high"}

    def test_level_mean_correct(self):
        me = main_effects(_results_df(), MetricRegistry.CYCLE_TIME)
        low_mean = me[me["level"] == "low"]["mean"].iloc[0]
        assert low_mean == pytest.approx(11.0)

    def test_rework_rate_metric(self):
        me = main_effects(_results_df(), MetricRegistry.REWORK_RATE)
        low_mean = me[me["level"] == "low"]["mean"].iloc[0]
        assert low_mean == pytest.approx(15.0)  # (10.0 + 20.0) / 2

    def test_rework_rate_sn_uses_floor(self):
        # REWORK_RATE.sn_floor = 0.01; the "high" group has rates [0.0, 10.0].
        # With the floor: −10·log10((0.01² + 10.01²)/2) = −10·log10(50.1001)
        # ≈ −16.998. WITHOUT the floor the 0.0 is filtered → −10·log10(10²) =
        # −20.0, so this pins main_effects reading metric.sn_floor.
        me = main_effects(_results_df(), MetricRegistry.REWORK_RATE)
        high_sn = me[me["level"] == "high"]["sn"].iloc[0]
        assert high_sn == pytest.approx(-16.998, abs=1e-3)


# ── sn_ranking ────────────────────────────────────────────────────────────────


class TestSnRanking:
    def _effects(self) -> pd.DataFrame:
        # f_a spans 6 S/N units, f_b spans 2 → f_a is the more influential factor.
        return pd.DataFrame(
            [
                {"factor": "f_a", "level": 1, "mean": 10.0, "sn": -20.0},
                {"factor": "f_a", "level": 2, "mean": 12.0, "sn": -26.0},
                {"factor": "f_b", "level": 1, "mean": 10.0, "sn": -21.0},
                {"factor": "f_b", "level": 2, "mean": 11.0, "sn": -23.0},
            ]
        )

    def test_delta_is_max_minus_min(self):
        ranked = sn_ranking(self._effects())
        assert ranked[ranked["factor"] == "f_a"]["delta_sn"].iloc[0] == pytest.approx(
            6.0
        )

    def test_most_influential_factor_ranks_first(self):
        ranked = sn_ranking(self._effects())
        assert ranked[ranked["factor"] == "f_a"]["rank"].iloc[0] == 1
        assert ranked[ranked["factor"] == "f_b"]["rank"].iloc[0] == 2

    def test_sorted_by_rank(self):
        ranked = sn_ranking(self._effects())
        assert list(ranked["factor"]) == ["f_a", "f_a", "f_b", "f_b"]

    def test_tied_deltas_share_rank(self):
        effects = pd.DataFrame(
            [
                {"factor": "f_a", "level": 1, "mean": 1.0, "sn": -20.0},
                {"factor": "f_a", "level": 2, "mean": 1.0, "sn": -22.0},
                {"factor": "f_b", "level": 1, "mean": 1.0, "sn": -30.0},
                {"factor": "f_b", "level": 2, "mean": 1.0, "sn": -32.0},
            ]
        )
        ranked = sn_ranking(effects)
        assert set(ranked["rank"]) == {1}

    def test_nan_delta_ranks_last(self):
        effects = pd.DataFrame(
            [
                {"factor": "f_a", "level": 1, "mean": 1.0, "sn": -20.0},
                {"factor": "f_a", "level": 2, "mean": 1.0, "sn": -26.0},
                {"factor": "f_nan", "level": 1, "mean": 1.0, "sn": float("nan")},
                {"factor": "f_nan", "level": 2, "mean": 1.0, "sn": float("nan")},
            ]
        )
        ranked = sn_ranking(effects)
        assert ranked[ranked["factor"] == "f_nan"]["rank"].iloc[0] == 2


# ── sn_export_table ───────────────────────────────────────────────────────────


class TestSnExportTable:
    _COLUMNS = ["Metric", "Factor", "Rank", "Δ S/N", "Level", "Level Mean", "Level S/N"]

    def _params(self) -> list[Parameter]:
        return [Parameter("f_a", "Factor A", [1, 2, 3])]

    def test_column_order(self):
        table = sn_export_table(_results_df(), self._params())
        assert list(table.columns) == self._COLUMNS

    def test_one_block_per_rankable_metric(self):
        table = sn_export_table(_results_df(), self._params())
        expected = {m.per_case_display_name for m in MetricRegistry.rankable()}
        assert set(table["Metric"]) == expected

    def test_factor_ids_translated_to_labels(self):
        table = sn_export_table(_results_df(), self._params())
        assert set(table["Factor"]) == {"Factor A"}

    def test_unlabelled_factor_id_passes_through(self):
        table = sn_export_table(_results_df(), [])
        assert set(table["Factor"]) == {"f_a"}

    def test_rank_one_first_within_each_metric(self):
        # A LOCAL two-factor frame: f_a separates every metric strongly, f_b not
        # at all → f_a is rank 1 and f_b rank 2 for each metric. On the single-
        # factor _results_df() every row is trivially rank 1, so a broken sort in
        # sn_ranking passes; here a mis-sort that surfaced the rank-2 factor first
        # would fail the assertion below.
        df = pd.DataFrame(
            [
                {
                    "scenario_id": "S01",
                    "replication": 0,
                    "f_a": "low",
                    "f_b": "p",
                    COL_MEAN_CYCLE_H: 10.0,
                    COL_MEAN_COST: 5.0,
                    COL_REWORK_RATE: 10.0,
                },
                {
                    "scenario_id": "S02",
                    "replication": 0,
                    "f_a": "low",
                    "f_b": "q",
                    COL_MEAN_CYCLE_H: 10.0,
                    COL_MEAN_COST: 5.0,
                    COL_REWORK_RATE: 10.0,
                },
                {
                    "scenario_id": "S03",
                    "replication": 0,
                    "f_a": "high",
                    "f_b": "p",
                    COL_MEAN_CYCLE_H: 30.0,
                    COL_MEAN_COST: 15.0,
                    COL_REWORK_RATE: 40.0,
                },
                {
                    "scenario_id": "S04",
                    "replication": 0,
                    "f_a": "high",
                    "f_b": "q",
                    COL_MEAN_CYCLE_H: 30.0,
                    COL_MEAN_COST: 15.0,
                    COL_REWORK_RATE: 40.0,
                },
            ]
        )
        table = sn_export_table(df, self._params())
        first_rows = table.groupby("Metric", sort=False).first()
        assert (first_rows["Rank"] == 1).all()
        # Per-metric: every metric must rank its two factors as exactly {1, 2}. A
        # global set(table["Rank"]) == {1, 2} is weaker — one metric collapsing to
        # {1, 1} is hidden by the union with a well-ranked metric.
        for _, group in table.groupby("Metric", sort=False):
            assert set(group["Rank"]) == {1, 2}


# ── rank ──────────────────────────────────────────────────────────────────────


def _sib_goal(metric: str, baseline: float) -> Goal:
    """Smaller-is-better goal with target=0.9×b, baseline_ref=b, worst=1.1×b."""
    from core.metrics import MetricDirection

    return Goal.from_baseline(metric, baseline, MetricDirection.SMALLER_IS_BETTER)


class TestRank:
    def test_per_goal_score_column_added(self):
        agg = pd.DataFrame([{"scenario_id": "S01", COL_MEAN_CYCLE_H_MEAN: 100.0}])
        ranked = rank(agg, [_sib_goal(COL_MEAN_CYCLE_H_MEAN, 100.0)])
        assert f"{COL_MEAN_CYCLE_H_MEAN}_score" in ranked.columns

    def test_overall_score_column_added(self):
        agg = pd.DataFrame([{"scenario_id": "S01", COL_MEAN_CYCLE_H_MEAN: 100.0}])
        ranked = rank(agg, [_sib_goal(COL_MEAN_CYCLE_H_MEAN, 100.0)])
        assert "score" in ranked.columns

    def test_score_at_target_is_100(self):
        # value = 0.9 × baseline → at target → score 100
        agg = pd.DataFrame([{"scenario_id": "S01", COL_MEAN_CYCLE_H_MEAN: 90.0}])
        ranked = rank(agg, [_sib_goal(COL_MEAN_CYCLE_H_MEAN, 100.0)])
        assert ranked.iloc[0][f"{COL_MEAN_CYCLE_H_MEAN}_score"] == pytest.approx(100.0)

    def test_score_at_threshold_is_50(self):
        # value = baseline_ref → score 50
        agg = pd.DataFrame([{"scenario_id": "S01", COL_MEAN_CYCLE_H_MEAN: 100.0}])
        ranked = rank(agg, [_sib_goal(COL_MEAN_CYCLE_H_MEAN, 100.0)])
        assert ranked.iloc[0][f"{COL_MEAN_CYCLE_H_MEAN}_score"] == pytest.approx(50.0)

    def test_score_at_worst_is_0(self):
        # value = 1.1 × baseline → at worst → score 0
        agg = pd.DataFrame([{"scenario_id": "S01", COL_MEAN_CYCLE_H_MEAN: 110.0}])
        ranked = rank(agg, [_sib_goal(COL_MEAN_CYCLE_H_MEAN, 100.0)])
        assert ranked.iloc[0][f"{COL_MEAN_CYCLE_H_MEAN}_score"] == pytest.approx(0.0)

    def test_nan_gets_score_0(self):
        agg = pd.DataFrame(
            [{"scenario_id": "S01", COL_MEAN_CYCLE_H_MEAN: float("nan")}]
        )
        ranked = rank(agg, [_sib_goal(COL_MEAN_CYCLE_H_MEAN, 100.0)])
        assert ranked.iloc[0][f"{COL_MEAN_CYCLE_H_MEAN}_score"] == pytest.approx(0.0)

    def test_overall_score_is_min_of_per_goal_scores(self):
        # Goal 1: value=90 (at target) → score 100
        # Goal 2: value=100 (at threshold) → score 50
        # Overall score = min(100, 50) = 50
        agg = pd.DataFrame(
            [
                {
                    "scenario_id": "S01",
                    COL_MEAN_CYCLE_H_MEAN: 90.0,
                    COL_MEAN_COST_MEAN: 100.0,
                }
            ]
        )
        goals = [
            _sib_goal(COL_MEAN_CYCLE_H_MEAN, 100.0),
            _sib_goal(COL_MEAN_COST_MEAN, 100.0),
        ]
        ranked = rank(agg, goals)
        assert ranked.iloc[0]["score"] == pytest.approx(50.0)

    def test_sorted_descending_by_score(self):
        # S01: at baseline_ref (score 50); S02: at target (score 100) → S02 ranked first
        agg = pd.DataFrame(
            [
                {"scenario_id": "S01", COL_MEAN_CYCLE_H_MEAN: 100.0},
                {"scenario_id": "S02", COL_MEAN_CYCLE_H_MEAN: 90.0},
            ]
        )
        ranked = rank(agg, [_sib_goal(COL_MEAN_CYCLE_H_MEAN, 100.0)])
        assert ranked.iloc[0]["scenario_id"] == "S02"

    def test_two_factor_goal_weighted_score(self):
        # Distinct scales + weight 0.75 make this discriminate both a weight-swap
        # and an argument-swap. Primary (mean) 90 = target → 100; secondary
        # (median) 220 = worst of 180/200/220 → 0. 0.75·100 + 0.25·0 = 75.
        #   weight-swap (0.25·100 + 0.75·0) → 25;
        #   arg-swap (primary.score(220)=0, secondary.score(90)=100) → 25.
        agg = pd.DataFrame(
            [
                {
                    "scenario_id": "S01",
                    COL_MEAN_CYCLE_H_MEAN: 90.0,
                    COL_MEDIAN_CYCLE_H_MEAN: 220.0,
                }
            ]
        )
        goal = Goal(
            metric=COL_MEAN_CYCLE_H_MEAN,
            target=90.0,
            baseline_ref=100.0,
            worst=110.0,
            secondary=_sib_goal(COL_MEDIAN_CYCLE_H_MEAN, 200.0),
            weight=0.75,
        )
        ranked = rank(agg, [goal])
        assert ranked.iloc[0][f"{COL_MEAN_CYCLE_H_MEAN}_score"] == pytest.approx(75.0)

    def test_two_factor_goal_participates_in_weakest_link(self):
        # Time goal (two-factor) scores 50; cost goal scores 100. Aggregate stays
        # the weakest-link min = 50 — weighting is intra-goal, never cross-goal.
        agg = pd.DataFrame(
            [
                {
                    "scenario_id": "S01",
                    COL_MEAN_CYCLE_H_MEAN: 90.0,
                    COL_MEDIAN_CYCLE_H_MEAN: 110.0,
                    COL_MEAN_COST_MEAN: 90.0,
                }
            ]
        )
        time_goal = Goal(
            metric=COL_MEAN_CYCLE_H_MEAN,
            target=90.0,
            baseline_ref=100.0,
            worst=110.0,
            secondary=_sib_goal(COL_MEDIAN_CYCLE_H_MEAN, 100.0),
            weight=0.5,
        )
        cost_goal = _sib_goal(COL_MEAN_COST_MEAN, 100.0)  # value 90 → score 100
        ranked = rank(agg, [time_goal, cost_goal])
        assert ranked.iloc[0]["score"] == pytest.approx(50.0)

    def test_empty_goals_produces_zero_score(self):
        agg = pd.DataFrame([{"scenario_id": "S01", COL_MEAN_CYCLE_H_MEAN: 90.0}])
        ranked = rank(agg, [])
        assert ranked.iloc[0]["score"] == pytest.approx(0.0)
