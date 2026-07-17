"""Interactive goal configuration for Panel 3.

Part of ui/interactive/, so this module renders st.* widgets directly. It owns
the goal-count radio, the per-slot metric pickers, the per-metric indicator
selector (which optional indicators contribute to a metric's score), the
editable absolute Target/Worst thresholds per selected indicator, and the
integer weight inputs that split a metric's score across its indicators —
returning a typed GoalConfig. Has no pure surface, so it is exercised manually
like app.py rather than unit-tested.

Threshold persistence: each threshold input's widget key embeds its seed value
(the §6 level-in-key pattern) plus a reset generation (see reset_goal_thresholds
for why a reset must re-key the widgets rather than scrub their state), so an
untouched input re-defaults whenever the baseline moves — every re-run shifts it
by simulation noise — while an edited value is written to the durable
ss.goal_threshold_overrides dict and survives both baseline movement and widget
unmount. (Streamlit garbage-collects the state of widgets that are not rendered;
the threshold rows unmount whenever no baseline is available — while the first
run is in flight, after a run whose baseline replications all failed, or after
switching demo → real — so a widget key alone cannot persist edits here.) The
overrides are log-level state — absolute thresholds are meaningless against a
different process — reset only when the log changes (via
app._clear_process_state()), never by clear_results().

Weights and indicator selection ride alongside the thresholds: a per-indicator
integer weight lives in the same overrides dict under the indicator column's
"weight" key (a stable key + generation, since its default never drifts with the
baseline); the chosen extra indicators live in the durable
ss.goal_indicator_selection dict (default-indicator column → extra columns), so a
selection survives rerun and unmount. Both are cleared on log reset —
reset_goal_thresholds() clears the overrides, reset_goal_selection() the
selection — and both are re-keyed by the reset generation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import streamlit as st

from core.goals import GOAL_IMPROVEMENT_PCT, Goal, MetricGoal
from core.metrics import IndicatorSpec, Metric, MetricRegistry

# Threshold-row column ratio: label | target | baseline | worst. Owned here, not
# imported from factor_levels: the goals grid stands in its own panel (3 · Goals),
# so it need not align with the factor grid. Weights render on their own row.
ROW_LAYOUT = [3, 1, 1, 1]


@dataclass
class GoalConfig:
    """The user's goal configuration for ranking.

    metrics: the chosen metrics, one per active slot (drives the Ranking tab's columns).
    scorable_goals: the validated MetricGoals — empty when no baseline exists yet,
    and missing any slot whose edited thresholds cannot score coherently.
    selected_extras: default-indicator column → chosen extra indicators (registry
    order), so the ranked table can show each selected indicator's column.
    """

    metrics: list[Metric]
    scorable_goals: list[MetricGoal]
    selected_extras: dict[str, list[IndicatorSpec]]


def reset_goal_thresholds() -> None:
    """Reset every threshold and weight input to its computed default.

    Clears the overrides (thresholds and weights) and bumps the generation
    embedded in every goal widget key. The re-keying is the load-bearing part:
    the browser keeps a mounted widget's user-set value keyed by the widget's
    identity and re-sends it with the next rerun (value= is only the *initial*
    value on the client side too), so any server-side reset that leaves the
    identity unchanged — an explicit st.rerun() after clearing, or deleting the
    widget-state keys in a callback — is undone by the re-sent value one
    interaction later. A new identity carries no client state, so the input
    re-seeds from the default. Shared by the Reset button (on_click) and
    app._clear_process_state() (log reset / replacement). The generation bump
    also re-keys the indicator multiselect, which re-reads its default from the
    durable selection dict (unchanged here — indicator choices survive a
    threshold reset; only reset_goal_selection clears them).
    """
    st.session_state.goal_threshold_overrides = {}
    st.session_state.goal_threshold_reset_generation += 1


def reset_goal_selection() -> None:
    """Clear the durable indicator-selection dict (log reset / replacement).

    Called only from app._clear_process_state(), alongside reset_goal_thresholds()
    (whose generation bump re-keys the multiselect so it re-reads the now-empty
    selection). Absolute indicator choices, like thresholds, are log-scoped.
    """
    st.session_state.goal_indicator_selection = {}


def _metric_slot_key(slot: int) -> str:
    """Session-state key of one slot's metric picker.

    Shared by the picker widget and the stale-slot guard in configure_goals,
    which must target the same key to re-default a slot whose stored metric
    was claimed by an earlier slot.
    """
    return f"goal_metric_{slot}"


def _metric_picker(slot: int, available: list[Metric]) -> Metric:
    """Render one slot's metric selectbox in the active container; return the pick."""
    return st.selectbox(
        f"Goal {slot + 1}",
        options=available,
        format_func=lambda metric: metric.per_case_display_name,
        key=_metric_slot_key(slot),
        label_visibility="collapsed",
    )


def _select_indicators(metric: Metric) -> list[IndicatorSpec]:
    """Render the extra-indicator multiselect; return the chosen extras in registry order.

    The locked default indicator is never an option (always in the score); a
    single-indicator metric (Cost) renders nothing and returns []. Options and
    the persisted selection are keyed by column string — no Metric-object
    comparison, so the st.selectbox value-copy identity trap cannot bite. The
    selection persists in ss.goal_indicator_selection (keyed by the default
    indicator's column) so it survives rerun and widget unmount.
    """
    extras = metric.extra_indicators
    if not extras:
        return []
    default_column = metric.per_case_column
    selection: dict[str, list[str]] = st.session_state.goal_indicator_selection
    by_column = {indicator.mean.column: indicator for indicator in extras}
    option_columns = list(by_column)  # registry order
    saved = selection.get(default_column, [])
    chosen = st.multiselect(
        f"{metric.per_case_compact_label} extra indicators",
        options=option_columns,
        default=[column for column in option_columns if column in saved],
        format_func=lambda column: by_column[column].compact_label,
        key=f"goal_indicators_{default_column}"
        f"_gen{st.session_state.goal_threshold_reset_generation}",
        label_visibility="collapsed",
        placeholder="Add indicators…",
    )
    selection[default_column] = chosen
    return [indicator for indicator in extras if indicator.mean.column in chosen]


def _threshold_input(
    column,
    indicator: IndicatorSpec,
    threshold_name: Literal["target", "worst"],
    default: float,
) -> float:
    """Render one editable threshold and return its value, persisting edits.

    The seed is the user's saved override when one exists, else the computed
    default. Embedding the seed in the key makes an untouched input track the
    moving default, while an edited input's key stabilises on its override.
    """
    overrides: dict[str, dict[str, float]] = st.session_state.goal_threshold_overrides
    indicator_column = indicator.mean.column
    decimal_places = indicator.decimal_places
    saved_override = overrides.get(indicator_column, {}).get(threshold_name)
    seed = (
        saved_override if saved_override is not None else round(default, decimal_places)
    )
    if indicator.upper_bound is not None:
        # A computed default can exceed the domain ceiling (worst = baseline
        # × 1.1 with a rework rate above ~91 %); a seed outside the widget's
        # bounds would crash number_input at render.
        seed = min(seed, indicator.upper_bound)
    value = float(
        column.number_input(
            f"{indicator.display_name} {threshold_name}",
            value=seed,
            min_value=0.0,
            max_value=indicator.upper_bound,
            step=10.0**-decimal_places,
            format=f"%.{decimal_places}f",
            key=f"goal_{threshold_name}_{indicator_column}_{seed}"
            f"_gen{st.session_state.goal_threshold_reset_generation}",
            label_visibility="collapsed",
        )
    )
    if value != seed:
        overrides.setdefault(indicator_column, {})[threshold_name] = value
    return value


def _baseline_display(column, indicator: IndicatorSpec, baseline_value: float) -> None:
    """Render the read-only measured baseline (the score-50 anchor).

    A disabled number_input, matching the frozen-factor precedent visually.
    Level-in-key works *for* us here: the baseline should re-default on every
    run, and the value-in-key makes it do so automatically.
    """
    decimal_places = indicator.decimal_places
    column.number_input(
        f"{indicator.display_name} baseline",
        value=baseline_value,
        format=f"%.{decimal_places}f",
        key=f"goal_baseline_{indicator.mean.column}_{baseline_value}",
        label_visibility="collapsed",
        disabled=True,
    )


def _coerce_weight(saved: float) -> int:
    """Read a stored weight as a valid int ≥ 1.

    session_state outlives the widget that wrote it, so a persisted weight is not
    guaranteed to be a positive int — a fractional value can survive, and
    int(round(0.5)) is 0, which MetricGoal.__post_init__ rejects. Clamp to ≥ 1 so
    a stale value can never crash Panel 3.
    """
    return max(1, int(round(saved)))


def _weight_input(container, indicator: IndicatorSpec) -> int:
    """Render one indicator's integer weight (≥ 1) and return it, persisting edits.

    The weight rides in goal_threshold_overrides under the indicator column's
    dict (key "weight"), so Reset and log reset already clear it. Its default
    never drifts with the baseline, so the key need not embed the seed — a stable
    key persists edits across re-runs and the override survives widget unmount.
    The reset generation is embedded so "Reset to defaults" re-keys it too.
    """
    overrides: dict[str, dict[str, float]] = st.session_state.goal_threshold_overrides
    indicator_column = indicator.mean.column
    saved = overrides.get(indicator_column, {}).get("weight")
    seed = _coerce_weight(saved) if saved is not None else 1
    value = int(
        container.number_input(
            f"{indicator.compact_label} weight",
            min_value=1,
            value=seed,
            step=1,
            key=f"goal_weight_{indicator_column}"
            f"_gen{st.session_state.goal_threshold_reset_generation}",
        )
    )
    if value != seed:
        overrides.setdefault(indicator_column, {})["weight"] = value
    return value


def _configure_indicator(
    target_cell,
    baseline_cell,
    worst_cell,
    indicator: IndicatorSpec,
    per_case_baseline: dict[str, float],
) -> Goal | None:
    """Render one indicator's threshold cells and return its validated Goal.

    Returns None — with a loud st.error naming the numbers — when the edited
    thresholds cannot score coherently (baseline outside the target–worst span).
    """
    default_goal = Goal.from_indicator(indicator, per_case_baseline)
    decimal_places = indicator.decimal_places
    # Rounded to the indicator's display precision so the value the user sees is
    # the value used for validation and as the Goal's score-50 anchor — a raw
    # baseline of 1.014 shown as 1.01 must not fail "worst = 1.01" validation.
    baseline_value = round(default_goal.baseline_ref, decimal_places)
    target = _threshold_input(target_cell, indicator, "target", default_goal.target)
    _baseline_display(baseline_cell, indicator, baseline_value)
    worst = _threshold_input(worst_cell, indicator, "worst", default_goal.worst)
    if not (min(target, worst) <= baseline_value <= max(target, worst)):
        st.error(
            f"{indicator.compact_label} indicator excluded from ranking: the "
            f"baseline ({baseline_value:.{decimal_places}f}) must lie between "
            f"target ({target:.{decimal_places}f}) and worst "
            f"({worst:.{decimal_places}f}).",
            icon="🚫",
        )
        return None
    return Goal(
        metric=indicator.mean.column,
        target=target,
        baseline_ref=baseline_value,
        worst=worst,
    )


def _weight_row(indicators: list[IndicatorSpec]) -> list[int]:
    """Render one integer weight per indicator + a normalised-split caption."""
    cells = st.columns(len(indicators))
    weights = [
        _weight_input(cell, indicator) for cell, indicator in zip(cells, indicators)
    ]
    total = sum(weights)
    st.caption(
        "Weights · "
        + " · ".join(
            f"{indicator.compact_label} {weight / total:.0%}"
            for indicator, weight in zip(indicators, weights)
        )
    )
    return weights


def _configure_metric_goal(
    indicators: list[IndicatorSpec],
    per_case_baseline: dict[str, float],
) -> MetricGoal | None:
    """Render a metric's selected indicators (thresholds + weights) → one MetricGoal.

    indicators[0] is the locked default; the rest are the user's chosen extras.
    Each gets a threshold row; when more than one is selected, a weight row lets
    the user split the metric's score across them (integer weights, normalised by
    sum). The whole slot is dropped (None) if any indicator's thresholds cannot
    score coherently.
    """
    # Short header labels — the 100/50/0 meaning lives in the panel caption, and
    # the goal columns are narrow (goals lay out side by side).
    header = st.columns(ROW_LAYOUT)
    header[0].caption("Indicator")
    header[1].caption("Target")
    header[2].caption("Baseline")
    header[3].caption("Worst")

    goals: list[Goal | None] = []
    for indicator in indicators:
        label_cell, target_cell, baseline_cell, worst_cell = st.columns(ROW_LAYOUT)
        label_cell.caption(indicator.compact_label)
        goals.append(
            _configure_indicator(
                target_cell, baseline_cell, worst_cell, indicator, per_case_baseline
            )
        )

    weights = _weight_row(indicators) if len(indicators) > 1 else [1] * len(indicators)

    if any(goal is None for goal in goals):
        return None
    return MetricGoal(
        indicator_goals=tuple(goal for goal in goals if goal is not None),
        weights=tuple(weights),
    )


def configure_goals(per_case_baseline: dict[str, float] | None) -> GoalConfig:
    """Render the goals block (count, metric per slot, indicators, thresholds, weights).

    per_case_baseline is the resolved per-case baseline (real or demo
    constants), or None in real mode before the first run / when every
    baseline replication failed — then only the metric pickers and indicator
    selectors render and no goals are scorable. Panel 3's "3 · Goals" header is
    rendered by app.py, like every sibling component's header.
    """
    if per_case_baseline is None:
        st.caption(
            f"Thresholds unlock once a run provides a baseline "
            f"(defaults: baseline ±{GOAL_IMPROVEMENT_PCT} %)."
        )
    else:
        st.caption(
            f"Score: 100 at target, 50 at baseline, 0 at worst. "
            f"Defaults: baseline ±{GOAL_IMPROVEMENT_PCT} %. A metric's score is the "
            f"weighted mean of its indicators."
        )
    rankable_metrics = MetricRegistry.rankable()
    goal_count = st.radio(
        "Goals",
        list(range(1, len(rankable_metrics) + 1)),
        index=0,
        horizontal=True,
        key="goal_count",
        label_visibility="collapsed",
    )

    chosen_metrics: list[Metric] = []
    scorable_goals: list[MetricGoal] = []
    selected_extras: dict[str, list[IndicatorSpec]] = {}
    # Lay the goals out side by side so adding a goal widens the panel instead of
    # lengthening it; a lone goal is held to half width so its threshold inputs
    # don't stretch across the whole page.
    goal_cols = st.columns([1, 1] if goal_count == 1 else [1] * goal_count)
    for slot in range(goal_count):
        available = [
            metric for metric in rankable_metrics if metric not in chosen_metrics
        ]
        slot_key = _metric_slot_key(slot)
        # Reset a slot whose stored metric was just claimed by an earlier slot.
        if st.session_state.get(slot_key) not in available:
            st.session_state[slot_key] = available[0]

        with goal_cols[slot]:
            metric = _metric_picker(slot, available)
            chosen_metrics.append(metric)
            extras = _select_indicators(metric)
            selected_extras[metric.per_case_column] = extras
            if per_case_baseline is not None:
                selected = [metric.default_indicator, *extras]
                metric_goal = _configure_metric_goal(selected, per_case_baseline)
                if metric_goal is not None:
                    scorable_goals.append(metric_goal)

    if per_case_baseline is not None:
        st.button(
            "Reset thresholds to defaults",
            key="goal_thresholds_reset",
            disabled=not st.session_state.goal_threshold_overrides,
            on_click=reset_goal_thresholds,
        )

    return GoalConfig(
        metrics=chosen_metrics,
        scorable_goals=scorable_goals,
        selected_extras=selected_extras,
    )
