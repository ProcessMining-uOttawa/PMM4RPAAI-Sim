"""Simulation result analysis: aggregation, Taguchi S/N, ranking, and baseline comparison."""

from __future__ import annotations
import math

import pandas as pd

from .constants import (
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
from .goals import Goal
from .metrics import Metric, MetricDirection, MetricRegistry
from .parameters import Parameter
from .constants import F_NUM_CASES


_NON_FACTOR_COLS = frozenset(
    {
        "scenario_id",
        "replication",
        COL_MEAN_CYCLE_H,
        COL_MEDIAN_CYCLE_H,
        COL_MEAN_COST,
        COL_TOTAL_CYCLE_S,
        COL_TOTAL_COST,
        COL_TOTAL_REWORK_COUNT,
        COL_REWORK_RATE,
        COL_TOTAL_BOT_FAILURE_COUNT,
    }
)


def _factor_cols(df: pd.DataFrame) -> list[str]:
    return [col for col in df.columns if col not in _NON_FACTOR_COLS]


def aggregate(results: pd.DataFrame) -> pd.DataFrame:
    """results: scenario_id, replication, + the metric cols (+ factor cols)."""
    factor_cols = _factor_cols(results)
    agg_spec: dict = {
        COL_MEAN_CYCLE_H_MEAN: (COL_MEAN_CYCLE_H, "mean"),
        "mean_cycle_h_std": (COL_MEAN_CYCLE_H, "std"),
        COL_MEDIAN_CYCLE_H_MEAN: (COL_MEDIAN_CYCLE_H, "mean"),
        COL_MEAN_COST_MEAN: (COL_MEAN_COST, "mean"),
        "mean_cost_std": (COL_MEAN_COST, "std"),
        COL_TOTAL_CYCLE_S_MEAN: (COL_TOTAL_CYCLE_S, "mean"),
        COL_TOTAL_COST_MEAN: (COL_TOTAL_COST, "mean"),
        COL_TOTAL_REWORK_COUNT_MEAN: (COL_TOTAL_REWORK_COUNT, "mean"),
        COL_REWORK_RATE_MEAN: (COL_REWORK_RATE, "mean"),
        COL_TOTAL_BOT_FAILURE_COUNT_MEAN: (COL_TOTAL_BOT_FAILURE_COUNT, "mean"),
    }
    return results.groupby(["scenario_id", *factor_cols], as_index=False).agg(
        **agg_spec
    )  # type: ignore[call-overload]


def _pct_delta(delta: float, baseline: float) -> float:
    return round(delta / baseline * 100, 1) if baseline != 0 else float("nan")


def compare_to_baseline(
    agg: pd.DataFrame, baseline_agg: dict[int, dict]
) -> pd.DataFrame:
    """Build a display DataFrame comparing each scenario's totals to its matching baseline.

    baseline_agg maps {n_cases: {col: value}} for each aggregate MetricSpec column.
    Scenarios are grouped by their cases level; each group is preceded by its baseline row.
    """
    specs = [m.aggregate for m in MetricRegistry.all() if m.aggregate is not None]
    num_cases_col = F_NUM_CASES if F_NUM_CASES in agg.columns else None
    rows: list[dict] = []
    for n_cases in sorted(baseline_agg):
        baseline = baseline_agg[n_cases]
        baseline_values = {
            spec.column: spec.display_fn(baseline[spec.column]) for spec in specs
        }
        baseline_row: dict = {
            "Scenario": f"Baseline ({n_cases} cases)",
            "Cases": n_cases,
        }
        for spec in specs:
            baseline_row[spec.display_name] = round(
                baseline_values[spec.column], spec.decimal_places
            )
            if spec.delta_name is not None:
                baseline_row[spec.delta_name] = 0.0
            if spec.pct_change_name is not None:
                baseline_row[spec.pct_change_name] = 0.0
        rows.append(baseline_row)
        group = agg if num_cases_col is None else agg[agg[num_cases_col] == n_cases]
        for _, row in group.iterrows():
            scenario_values = {
                spec.column: spec.display_fn(row[spec.column]) for spec in specs
            }
            scenario_row: dict = {"Scenario": row["scenario_id"], "Cases": n_cases}
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
    """For each factor × level: mean metric and S/N ratio."""
    if metric.per_case is None:
        raise ValueError(
            f"main_effects() requires a metric with per_case data; got {metric}"
        )
    per_case = metric.per_case
    col = per_case.results_column
    direction = per_case.mean.direction
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


def rank(agg: pd.DataFrame, goals: list[Goal]) -> pd.DataFrame:
    """Adds per-goal '{metric}_score' columns plus an aggregate 'score'.

    Per-goal score: piecewise linear 0–100 (100 = target met, 50 = at baseline, 0 = at worst).
    Aggregate score: min of all per-goal scores (weakest-link rule).
    Scenarios are sorted descending by aggregate score (higher is better).
    """
    out = agg.copy()
    per_goal_scores: list[pd.Series] = []
    for goal in goals:
        if goal.secondary is None:
            goal_scores = out[goal.metric].apply(goal.score)
        else:
            # Two-factor goal: weighted sum of the two factors' scores, each
            # judged against its own breakpoints. The score column stays keyed by
            # the PRIMARY metric so prepare_ranked_display picks it up unchanged.
            secondary = goal.secondary
            goal_scores = out.apply(
                lambda row, goal=goal, secondary=secondary: goal.weighted_score(
                    row[goal.metric], row[secondary.metric]
                ),
                axis=1,
            )
        out[f"{goal.metric}_score"] = goal_scores.round(1)
        per_goal_scores.append(goal_scores)
    if per_goal_scores:
        out["score"] = pd.concat(per_goal_scores, axis=1).min(axis=1).round(1)
    else:
        out["score"] = 0.0
    return out.sort_values("score", ascending=False)
