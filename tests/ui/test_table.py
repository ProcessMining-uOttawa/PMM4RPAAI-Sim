"""Tests for ui/table.py — prepare_ranked_display column selection and renaming,
plus the fidelity panel's per-replication and comparison display prep."""

from __future__ import annotations

import pandas as pd

from core.constants import (
    COL_MAX_CYCLE_H,
    COL_MEAN_COST_MEAN,
    COL_MEAN_CYCLE_H_MEAN,
    COL_MEDIAN_CYCLE_H_MEAN,
    COL_MIN_CYCLE_H,
)
from core.metrics import MetricRegistry
from core.parameters import Parameter
from ui.table import (
    prepare_fidelity_display,
    prepare_ranked_display,
    prepare_replication_display,
)

# The median cycle-time indicator (an extra of the CYCLE_TIME metric).
_MEDIAN_INDICATOR = next(
    ind
    for ind in MetricRegistry.CYCLE_TIME.extra_indicators
    if ind.mean.column == COL_MEDIAN_CYCLE_H_MEAN
)


def _ranked() -> pd.DataFrame:
    """Minimal rank() output: scenario, the cycle-time KPI, its goal score, overall."""
    return pd.DataFrame(
        {
            "scenario_id": ["S01", "S02"],
            COL_MEAN_CYCLE_H_MEAN: [5.0, 6.0],
            f"{COL_MEAN_CYCLE_H_MEAN}_score": [100.0, 50.0],
            "score": [100.0, 50.0],
        }
    )


def _factor_param() -> Parameter:
    return Parameter(
        id="pct_auto", label="Auto %", levels=[25, 50, 75], kind="percentage"
    )


class TestPrepareRankedDisplay:
    def test_columns_and_order(self):
        result = prepare_ranked_display(
            _ranked(), [MetricRegistry.CYCLE_TIME], [], {}, show_factors=False
        )
        assert list(result.columns) == [
            "rank",
            "Scenario",
            "Cycle Time (h/case)",
            "Cycle Time Score",
            "Overall Score",
        ]

    def test_rank_is_one_based(self):
        result = prepare_ranked_display(_ranked(), [MetricRegistry.CYCLE_TIME], [], {})
        assert result["rank"].tolist() == [1, 2]

    def test_scenario_id_renamed(self):
        result = prepare_ranked_display(_ranked(), [MetricRegistry.CYCLE_TIME], [], {})
        assert "Scenario" in result.columns
        assert "scenario_id" not in result.columns

    def test_factors_hidden_by_default(self):
        ranked = _ranked()
        ranked["pct_auto"] = [25, 50]
        result = prepare_ranked_display(
            ranked, [MetricRegistry.CYCLE_TIME], [_factor_param()], {}
        )
        assert "Auto %" not in result.columns

    def test_factors_shown_when_requested(self):
        ranked = _ranked()
        ranked["pct_auto"] = [25, 50]
        result = prepare_ranked_display(
            ranked,
            [MetricRegistry.CYCLE_TIME],
            [_factor_param()],
            {},
            show_factors=True,
        )
        assert "Auto %" in result.columns

    def test_frozen_factor_excluded_even_when_shown(self):
        # The `if not p.frozen` guard: a frozen factor is held constant across
        # scenarios (excluded from the OA) so it carries no per-scenario signal
        # and must not appear as a column even with show_factors=True. Both
        # columns exist in `ranked`, so only the guard can drop the frozen one.
        ranked = _ranked()
        ranked["pct_auto"] = [25, 50]
        ranked["num_cases"] = [100, 100]
        frozen = Parameter(
            id="num_cases",
            label="Cases (frozen)",
            levels=[100, 100, 100],
            kind="categorical",
            frozen=True,
        )
        result = prepare_ranked_display(
            ranked,
            [MetricRegistry.CYCLE_TIME],
            [_factor_param(), frozen],
            {},
            show_factors=True,
        )
        assert "Auto %" in result.columns
        assert "Cases (frozen)" not in result.columns

    def test_factor_columns_between_scenario_and_kpis(self):
        # Contract order: rank · Scenario · [factor cols] · KPI means · … — pin
        # the factor column's position so a reorder that shifts factors after the
        # KPIs is caught.
        ranked = _ranked()
        ranked["pct_auto"] = [25, 50]
        result = prepare_ranked_display(
            ranked,
            [MetricRegistry.CYCLE_TIME],
            [_factor_param()],
            {},
            show_factors=True,
        )
        cols = list(result.columns)
        assert (
            cols.index("Scenario")
            < cols.index("Auto %")
            < cols.index("Cycle Time (h/case)")
        )

    def test_metric_absent_from_ranked_is_skipped(self):
        # Only cycle-time columns exist; Cost's KPI column does not, so it must be
        # silently filtered out (the `col in ranked.columns` guard).
        result = prepare_ranked_display(_ranked(), [MetricRegistry.CYCLE_TIME], [], {})
        assert "Cost ($/case)" not in result.columns

    def test_selected_extra_shown_beside_its_metric(self):
        # A chosen extra indicator (median) appears right after the metric's
        # default KPI so its input to the combined score is visible.
        ranked = _ranked()
        ranked[COL_MEDIAN_CYCLE_H_MEAN] = [4.0, 5.0]
        selected_extras = {COL_MEAN_CYCLE_H_MEAN: [_MEDIAN_INDICATOR]}
        result = prepare_ranked_display(
            ranked, [MetricRegistry.CYCLE_TIME], [], selected_extras
        )
        cols = list(result.columns)
        assert "Median Cycle Time (h/case)" in cols
        assert (
            cols.index("Median Cycle Time (h/case)")
            == cols.index("Cycle Time (h/case)") + 1
        )

    def test_unselected_extra_hidden(self):
        # With no extras selected, the median column is suppressed even though it
        # exists in `ranked` — it is an indicator, not a standalone KPI.
        ranked = _ranked()
        ranked[COL_MEDIAN_CYCLE_H_MEAN] = [4.0, 5.0]
        result = prepare_ranked_display(ranked, [MetricRegistry.CYCLE_TIME], [], {})
        assert "Median Cycle Time (h/case)" not in result.columns

    def test_dropped_goal_keeps_kpi_but_skips_score_column(self):
        # The dropped-goal shape from ui/interactive/goal_config.py: a goal whose
        # thresholds failed validation is excluded from rank(), so its metric is
        # in goal_metrics and its KPI column exists but its _score column does
        # not — the display must keep the KPI and skip only the score.
        ranked = _ranked()
        ranked[COL_MEAN_COST_MEAN] = [3.0, 4.0]  # Cost KPI present, no cost score
        result = prepare_ranked_display(
            ranked, [MetricRegistry.CYCLE_TIME, MetricRegistry.COST], [], {}
        )
        assert "Cost ($/case)" in result.columns
        assert "Cost Score" not in result.columns
        assert "Cycle Time Score" in result.columns


_ALL_INDICATORS = [
    indicator for metric in MetricRegistry.all() for indicator in metric.indicators
]
# The display culls the min/max cycle extremes (see ui/table.py); the input
# frame still carries them so the exclusion is exercised, not vacuous.
_DISPLAYED_INDICATORS = [
    indicator
    for indicator in _ALL_INDICATORS
    if indicator.results_column not in (COL_MIN_CYCLE_H, COL_MAX_CYCLE_H)
]


def _replication_results() -> pd.DataFrame:
    """A two-replication as-discovered results frame covering every indicator.

    Values are distinct per column (offset by indicator position) so a
    source-to-display column misrouting cannot pass unnoticed.
    """
    data: dict = {"replication": [0, 1]}
    for offset, indicator in enumerate(_ALL_INDICATORS):
        data[indicator.results_column] = [1.23456 + offset, 2.34567 + offset]
    return pd.DataFrame(data)


class TestPrepareReplicationDisplay:
    def test_display_columns_exclude_the_cycle_extremes(self):
        # Exact equality pins both halves: every non-extreme registered
        # indicator appears, and the min/max cycle columns present in the
        # input do not.
        result = prepare_replication_display(_replication_results())
        expected = ["Replication"] + [
            indicator.mean.display_name for indicator in _DISPLAYED_INDICATORS
        ]
        assert list(result.columns) == expected

    def test_values_rounded_to_spec_decimals(self):
        result = prepare_replication_display(_replication_results())
        for offset, indicator in enumerate(_ALL_INDICATORS):
            if indicator not in _DISPLAYED_INDICATORS:
                continue
            spec = indicator.mean
            expected = [
                round(spec.display_fn(raw + offset), spec.decimal_places)
                for raw in (1.23456, 2.34567)
            ]
            assert result[spec.display_name].tolist() == expected


def _fidelity_frame() -> pd.DataFrame:
    """A two-row analysis.fidelity_table() output: one std, one NaN (single rep)."""
    return pd.DataFrame(
        {
            "Metric": ["Cycle Time (h/case)", "Rework Rate (%)"],
            "Log (observed)": [24.0, 2400.0],
            "Model (mean)": [26.0, 2600.0],
            "Model (std)": [1.0, float("nan")],
            "Δ": [2.0, 200.0],
            "Δ %": [8.3, 8.3],
        }
    )


class TestPrepareFidelityDisplay:
    def test_mean_and_std_fold_into_one_column(self):
        result = prepare_fidelity_display(_fidelity_frame(), n_reps=3)
        model_col = "Model (mean ± std of 3 reps)"
        assert list(result.columns) == [
            "Metric",
            "Log (observed)",
            model_col,
            "Δ",
            "Δ %",
        ]
        assert result[model_col].tolist()[0] == "26.0 ± 1.0"

    def test_nan_std_renders_a_dash(self):
        result = prepare_fidelity_display(_fidelity_frame(), n_reps=3)
        assert result["Model (mean ± std of 3 reps)"].tolist()[1] == "2600.0 ± —"

    def test_observed_and_delta_columns_pass_through(self):
        result = prepare_fidelity_display(_fidelity_frame(), n_reps=3)
        assert result["Metric"].tolist() == [
            "Cycle Time (h/case)",
            "Rework Rate (%)",
        ]
        assert result["Log (observed)"].tolist() == [24.0, 2400.0]
        assert result["Δ"].tolist() == [2.0, 200.0]
        assert result["Δ %"].tolist() == [8.3, 8.3]
