"""Simulation result analysis: aggregation, Taguchi S/N, ranking, and baseline comparison."""

from __future__ import annotations
import math

import pandas as pd

from .constants import (
    COL_TOTAL_CYCLE_S,
    COL_TOTAL_COST,
    COL_TOTAL_CYCLE_S_MEAN,
    COL_TOTAL_COST_MEAN,
    COL_TOTAL_REWORK_COUNT,
    COL_TOTAL_REWORK_COUNT_MEAN,
    COL_TOTAL_BOT_FAILURE_COUNT,
    COL_TOTAL_BOT_FAILURE_COUNT_MEAN,
)
from .goals import MetricGoal
from .metrics import Metric, MetricDirection, MetricRegistry
from .parameters import Parameter


# The run-total raw columns — hand-listed because they never grow with the
# indicator set (indicators never create a total; see CLAUDE.md §8). Shared by
# _NON_FACTOR_COLS and aggregate()'s totals so the pairing lives in one place.
_TOTAL_RESULT_COLS: tuple[tuple[str, str], ...] = (
    (COL_TOTAL_CYCLE_S_MEAN, COL_TOTAL_CYCLE_S),
    (COL_TOTAL_COST_MEAN, COL_TOTAL_COST),
    (COL_TOTAL_REWORK_COUNT_MEAN, COL_TOTAL_REWORK_COUNT),
    (COL_TOTAL_BOT_FAILURE_COUNT_MEAN, COL_TOTAL_BOT_FAILURE_COUNT),
)

# Non-factor columns are everything the results DataFrame carries that is NOT a
# Taguchi factor: the two structural columns, every registered indicator's raw
# per-replication column, and the run totals. Registry-derived so a new
# indicator never has to be added here — omitting one would make aggregate()
# group by it as a phantom factor.
_NON_FACTOR_COLS = frozenset(
    {"scenario_id", "replication"}
    | {raw for _, raw in _TOTAL_RESULT_COLS}
    | {
        indicator.results_column
        for metric in MetricRegistry.all()
        for indicator in metric.indicators
    }
)


def _factor_cols(df: pd.DataFrame) -> list[str]:
    return [col for col in df.columns if col not in _NON_FACTOR_COLS]


def aggregate(results: pd.DataFrame) -> pd.DataFrame:
    """results: scenario_id, replication, + the metric cols (+ factor cols)."""
    factor_cols = _factor_cols(results)
    agg_spec: dict = {}
    for metric in MetricRegistry.all():
        for indicator in metric.indicators:
            agg_spec[indicator.mean.column] = (indicator.results_column, "mean")
    for out_col, raw_col in _TOTAL_RESULT_COLS:
        agg_spec[out_col] = (raw_col, "mean")
    return results.groupby(["scenario_id", *factor_cols], as_index=False).agg(
        **agg_spec
    )  # type: ignore[call-overload]


def _pct_delta(delta: float, baseline: float) -> float:
    return round(delta / baseline * 100, 1) if baseline != 0 else float("nan")


def compare_to_baseline(
    agg: pd.DataFrame, baseline_agg: dict[str, float]
) -> pd.DataFrame:
    """Build a display DataFrame comparing every scenario's totals to the baseline.

    baseline_agg is one flat {col: value} record covering each aggregate
    MetricSpec column; every scenario ran at the same case count, so all rows
    compare against the single baseline row that precedes them.
    """
    specs = [m.aggregate for m in MetricRegistry.all() if m.aggregate is not None]
    baseline_values = {
        spec.column: spec.display_fn(baseline_agg[spec.column]) for spec in specs
    }
    baseline_row: dict = {"Scenario": "Baseline"}
    for spec in specs:
        baseline_row[spec.display_name] = round(
            baseline_values[spec.column], spec.decimal_places
        )
        if spec.delta_name is not None:
            baseline_row[spec.delta_name] = 0.0
        if spec.pct_change_name is not None:
            baseline_row[spec.pct_change_name] = 0.0
    rows: list[dict] = [baseline_row]
    for _, row in agg.iterrows():
        scenario_values = {
            spec.column: spec.display_fn(row[spec.column]) for spec in specs
        }
        scenario_row: dict = {"Scenario": row["scenario_id"]}
        for spec in specs:
            delta = scenario_values[spec.column] - baseline_values[spec.column]
            scenario_row[spec.display_name] = round(
                scenario_values[spec.column], spec.decimal_places
            )
            if spec.delta_name is not None:
                scenario_row[spec.delta_name] = round(delta, spec.decimal_places)
            if spec.pct_change_name is not None:
                scenario_row[spec.pct_change_name] = _pct_delta(
                    delta, baseline_values[spec.column]
                )
        rows.append(scenario_row)
    return pd.DataFrame(rows)


def fidelity_table(
    observed: dict[str, float], sim_results: pd.DataFrame
) -> pd.DataFrame:
    """Build the model-fidelity display frame: uploaded log vs as-discovered runs.

    observed is the flat {column: value} record of ObservedStats (the
    baseline_agg seam precedent); sim_results is the per-replication frame from
    an as-discovered run, so "Model (mean)"/"Model (std)" summarise across
    replications (std is NaN at one replication — the caller renders that).
    Columns are numeric; formatting is the panel's job.

    The row set is an explicit inclusion list — the four cycle indicators, the
    cycle total, and the rework rate. Cost has no observed ground truth and
    arrival-anchored spans are absent from logs entirely (left truncation), so
    neither can appear. Under the fidelity check's pinned case count the total
    row's Δ% equals the mean row's by construction (total = mean × n × 3600 on
    both sides); it is kept for familiarity, not independent signal.
    """
    cycle = MetricRegistry.CYCLE_TIME
    assert cycle.aggregate is not None  # CYCLE_TIME always defines its total spec
    rework = MetricRegistry.REWORK_RATE.default_indicator
    specs = [(ind.results_column, ind.mean) for ind in cycle.indicators] + [
        (COL_TOTAL_CYCLE_S, cycle.aggregate),
        (rework.results_column, rework.mean),
    ]
    rows: list[dict] = []
    for column, spec in specs:
        observed_value = spec.display_fn(observed[column])
        sim = sim_results[column]
        sim_mean = spec.display_fn(float(sim.mean()))
        sim_std = spec.display_fn(float(sim.std()))
        delta = sim_mean - observed_value
        rows.append(
            {
                "Metric": spec.display_name,
                "Log (observed)": round(observed_value, spec.decimal_places),
                "Model (mean)": round(sim_mean, spec.decimal_places),
                "Model (std)": round(sim_std, spec.decimal_places),
                "Δ": round(delta, spec.decimal_places),
                "Δ %": _pct_delta(delta, observed_value),
            }
        )
    return pd.DataFrame(rows)


def signal_to_noise(
    values,
    direction: MetricDirection = MetricDirection.SMALLER_IS_BETTER,
    floor: float = 0.0,
) -> float:
    adjusted = [v + floor for v in values if v is not None and v + floor > 0]
    if not adjusted:
        return float("nan")
    if direction == MetricDirection.SMALLER_IS_BETTER:
        return -10 * math.log10(sum(v * v for v in adjusted) / len(adjusted))
    if direction == MetricDirection.LARGER_IS_BETTER:
        return -10 * math.log10(sum(1 / (v * v) for v in adjusted) / len(adjusted))
    raise ValueError(direction)


def main_effects(results: pd.DataFrame, metric: Metric) -> pd.DataFrame:
    """For each factor × level: mean metric and S/N ratio.

    Scored on the metric's default indicator — the ranked, S/N-analysed one.
    """
    if not metric.indicators:
        raise ValueError(
            f"main_effects() requires a metric with indicators; got {metric}"
        )
    indicator = metric.default_indicator
    col = indicator.results_column
    direction = indicator.mean.direction
    floor = metric.sn_floor
    rows = []
    for factor in _factor_cols(results):
        for level, level_rows in results.groupby(factor):
            rows.append(
                {
                    "factor": factor,
                    "level": level,
                    "mean": level_rows[col].mean(),
                    "sn": signal_to_noise(level_rows[col].tolist(), direction, floor),
                }
            )
    return pd.DataFrame(rows)


def sn_ranking(effects: pd.DataFrame) -> pd.DataFrame:
    """Add per-factor S/N delta and influence rank to a main_effects() frame.

    delta_sn is max − min of a factor's level S/N values; rank 1 is the largest
    delta — the most influential factor, the classic Taguchi response-table
    ranking. Factors whose delta is NaN (all-NaN S/N) rank last. Rows are
    sorted by rank; within a factor the level order from main_effects() is kept.
    """
    factor_deltas = effects.groupby("factor")["sn"].agg(
        lambda sn_values: sn_values.max() - sn_values.min()
    )
    factor_ranks = factor_deltas.rank(
        method="dense", ascending=False, na_option="bottom"
    )
    out = effects.copy()
    out["delta_sn"] = out["factor"].map(factor_deltas)
    out["rank"] = out["factor"].map(factor_ranks).astype(int)
    return out.sort_values(["rank", "factor"], kind="stable").reset_index(drop=True)


def sn_export_table(results: pd.DataFrame, parameters: list[Parameter]) -> pd.DataFrame:
    """Ranked S/N response table across all rankable metrics, display-named.

    One row per metric × factor × level. Rank 1 is the factor with the largest
    S/N delta for that metric (most influential). Factor ids are translated to
    their display labels. Display-named columns follow the compare_to_baseline
    precedent — this frame is consumed as-is by the S/N CSV export.
    """
    label_map = {p.id: p.label for p in parameters}
    frames = []
    for metric in MetricRegistry.rankable():
        ranked = sn_ranking(main_effects(results, metric))
        ranked.insert(0, "Metric", metric.per_case_display_name)
        frames.append(ranked)
    table = pd.concat(frames, ignore_index=True)
    table["factor"] = table["factor"].map(lambda factor: label_map.get(factor, factor))
    table = table.rename(
        columns={
            "factor": "Factor",
            "rank": "Rank",
            "delta_sn": "Δ S/N",
            "level": "Level",
            "mean": "Level Mean",
            "sn": "Level S/N",
        }
    )
    return table[
        ["Metric", "Factor", "Rank", "Δ S/N", "Level", "Level Mean", "Level S/N"]
    ]


def rank(agg: pd.DataFrame, goals: list[MetricGoal]) -> pd.DataFrame:
    """Adds a per-metric '{column}_score' column plus an aggregate 'score'.

    Per-metric score: MetricGoal.score — the weight-normalised mean of its
    indicators' piecewise-linear scores (0–100). One uniform path for one- and
    many-indicator goals; the score column is keyed by the default indicator so
    prepare_ranked_display picks it up unchanged.
    Aggregate score: min of all per-metric scores (weakest-link rule).
    Scenarios are sorted descending by aggregate score (higher is better).
    """
    out = agg.copy()
    per_goal_scores: list[pd.Series] = []
    for goal in goals:
        goal_scores = out.apply(lambda row, goal=goal: goal.score(row), axis=1).round(1)
        out[goal.score_column] = goal_scores
        per_goal_scores.append(goal_scores)
    if per_goal_scores:
        out["score"] = pd.concat(per_goal_scores, axis=1).min(axis=1).round(1)
    else:
        out["score"] = 0.0
    return out.sort_values("score", ascending=False)
