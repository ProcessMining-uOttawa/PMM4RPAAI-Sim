"""Interactive goal configuration for Panel 3.

Part of ui/interactive/, so this module renders st.* widgets directly. It owns
the goal-count radio, the per-slot metric pickers, the editable absolute
threshold inputs (target / worst) that parameterize goal scoring, and — for the
two-factor time goal — a second (median) threshold row plus a mean/median weight
slider, returning a typed GoalConfig. Has no pure surface, so it is exercised manually like app.py
rather than unit-tested.

Threshold persistence: each input's widget key embeds its seed value (the §6
level-in-key pattern) plus a reset generation (see reset_goal_thresholds for
why a reset must re-key the widgets rather than scrub their state), so an
untouched input re-defaults whenever the baseline moves — every re-run shifts
it by simulation noise — while an edited value is written to the durable
ss.goal_threshold_overrides dict and survives both baseline movement and
widget unmount. (Streamlit garbage-collects the state of widgets that are not
rendered; the inputs unmount whenever no baseline is available — while the
first run is in flight, after a run whose baseline replications all failed, or
after switching demo → real — so a widget key alone cannot persist edits
here.) The overrides are log-level state — absolute thresholds are meaningless
against a different process — reset only when the log changes (via
app._clear_process_state()), never by clear_results(). Switching demo → real
mid-session hides the inputs until the first real run completes; overrides
persist across the toggle because the loaded model is unchanged. The two-factor
time goal's mean/median weight rides in the same overrides dict (under the
primary column's "weight" key), so Reset and log reset clear it identically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import streamlit as st

from core.goals import GOAL_IMPROVEMENT_PCT, Goal
from core.metrics import Metric, MetricRegistry

# Goal-row column ratio: label | target | baseline | worst. Owned here, not
# imported from factor_levels: the goals grid stands in its own panel (3 · Goals)
# now, so it need not align with the factor grid — the previous shared-ROW_LAYOUT
# coupling only existed to keep the two grids column-aligned when stacked in one
# panel.
ROW_LAYOUT = [3, 1, 1, 1]


@dataclass
class GoalConfig:
    """The user's goal configuration for ranking.

    metrics: the chosen metrics, one per active slot (drives the Ranking tab's columns).
    scorable_goals: the validated Goals — empty when no baseline exists yet,
    and missing any slot whose edited thresholds cannot score coherently.
    """

    metrics: list[Metric]
    scorable_goals: list[Goal]


def reset_goal_thresholds() -> None:
    """Reset every threshold input to its computed default.

    Clears the overrides and bumps the generation embedded in every threshold
    widget key. The re-keying is the load-bearing part: the browser keeps a
    mounted widget's user-set value keyed by the widget's identity and
    re-sends it with the next rerun (value= is only the *initial* value on
    the client side too), so any server-side reset that leaves the identity
    unchanged — an explicit st.rerun() after clearing, or deleting the
    widget-state keys in a callback — is undone by the re-sent value one
    interaction later, which the value != seed check then re-writes into
    overrides. A new identity carries no client state, so the input re-seeds
    from the default. Shared by the Reset button (on_click) and
    app._clear_process_state() (log reset / replacement), so no reset site
    leaves re-keyable client state behind.
    """
    st.session_state.goal_threshold_overrides = {}
    st.session_state.goal_threshold_reset_generation += 1


def _metric_slot_key(slot: int) -> str:
    """Session-state key of one slot's metric picker.

    Shared by the picker widget and the stale-slot guard in configure_goals,
    which must target the same key to re-default a slot whose stored metric
    was claimed by an earlier slot.
    """
    return f"goal_metric_{slot}"


def _metric_picker(container, slot: int, available: list[Metric]) -> Metric:
    """Render one slot's metric selectbox in the given container; return the pick."""
    return container.selectbox(
        f"Goal {slot + 1}",
        options=available,
        format_func=lambda metric: metric.per_case_display_name,
        key=_metric_slot_key(slot),
        label_visibility="collapsed",
    )


def _threshold_input(
    column, metric: Metric, threshold_name: Literal["target", "worst"], default: float
) -> float:
    """Render one editable threshold and return its value, persisting edits.

    The seed is the user's saved override when one exists, else the computed
    default. Embedding the seed in the key makes an untouched input track the
    moving default, while an edited input's key stabilises on its override.
    """
    overrides: dict[str, dict[str, float]] = st.session_state.goal_threshold_overrides
    metric_column = metric.per_case_column
    decimal_places = metric.per_case_decimal_places
    saved_override = overrides.get(metric_column, {}).get(threshold_name)
    seed = (
        saved_override if saved_override is not None else round(default, decimal_places)
    )
    if metric.upper_bound is not None:
        # A computed default can exceed the domain ceiling (worst = baseline
        # × 1.1 with a rework rate above ~91 %); a seed outside the widget's
        # bounds would crash number_input at render.
        seed = min(seed, metric.upper_bound)
    value = float(
        column.number_input(
            f"{metric.per_case_display_name} {threshold_name}",
            value=seed,
            min_value=0.0,
            max_value=metric.upper_bound,
            step=10.0**-decimal_places,
            format=f"%.{decimal_places}f",
            key=f"goal_{threshold_name}_{metric_column}_{seed}"
            f"_gen{st.session_state.goal_threshold_reset_generation}",
            label_visibility="collapsed",
        )
    )
    if value != seed:
        overrides.setdefault(metric_column, {})[threshold_name] = value
    return value


def _baseline_display(column, metric: Metric, baseline_value: float) -> None:
    """Render the read-only measured baseline (the score-50 anchor).

    A disabled number_input, matching the frozen-factor precedent visually.
    Level-in-key works *for* us here: the baseline should re-default on every
    run, and the value-in-key makes it do so automatically.
    """
    decimal_places = metric.per_case_decimal_places
    column.number_input(
        f"{metric.per_case_display_name} baseline",
        value=baseline_value,
        format=f"%.{decimal_places}f",
        key=f"goal_baseline_{metric.per_case_column}_{baseline_value}",
        label_visibility="collapsed",
        disabled=True,
    )


def _weight_input(container, primary_column: str, default: float = 0.5) -> float:
    """Render a two-factor goal's primary weight (0–1 slider), persisting edits.

    The weight rides in goal_threshold_overrides under the primary column's dict
    (key "weight"), so the Reset button and log reset already clear it. Unlike a
    threshold it has a fixed default that never drifts with the baseline, so its
    key need not embed the seed — a stable key persists edits across re-runs and
    the override survives widget unmount (demo → real). The reset generation is
    embedded so "Reset to defaults" re-keys it too.
    """
    overrides: dict[str, dict[str, float]] = st.session_state.goal_threshold_overrides
    saved = overrides.get(primary_column, {}).get("weight")
    seed = saved if saved is not None else default
    value = float(
        container.slider(
            "Mean weight (vs median)",
            min_value=0.0,
            max_value=1.0,
            value=seed,
            step=0.05,
            key=f"goal_weight_{primary_column}"
            f"_gen{st.session_state.goal_threshold_reset_generation}",
            label_visibility="collapsed",
        )
    )
    if value != seed:
        overrides.setdefault(primary_column, {})["weight"] = value
    return value


def _configure_factor(
    target_cell,
    baseline_cell,
    worst_cell,
    metric: Metric,
    per_case_baseline: dict[str, float],
) -> Goal | None:
    """Render one factor's threshold cells and return its validated single-factor Goal.

    Returns None — with a loud st.error naming the numbers — when the edited
    thresholds cannot score coherently (baseline outside the target–worst span).
    """
    default_goal = Goal.from_metric(metric, per_case_baseline)
    decimal_places = metric.per_case_decimal_places
    # Rounded to the metric's display precision so the value the user sees is
    # the value used for validation and as the Goal's score-50 anchor — a raw
    # baseline of 1.014 shown as 1.01 must not fail "worst = 1.01" validation.
    baseline_value = round(default_goal.baseline_ref, decimal_places)
    target = _threshold_input(target_cell, metric, "target", default_goal.target)
    _baseline_display(baseline_cell, metric, baseline_value)
    worst = _threshold_input(worst_cell, metric, "worst", default_goal.worst)
    if not (min(target, worst) <= baseline_value <= max(target, worst)):
        st.error(
            f"{metric.per_case_compact_label} goal excluded from ranking: the "
            f"baseline ({baseline_value:.{decimal_places}f}) must lie between "
            f"target ({target:.{decimal_places}f}) and worst "
            f"({worst:.{decimal_places}f}).",
            icon="🚫",
        )
        return None
    return Goal(
        metric=metric.per_case_column,
        target=target,
        baseline_ref=baseline_value,
        worst=worst,
    )


def _configure_slot_goal(
    target_cell,
    baseline_cell,
    worst_cell,
    metric: Metric,
    per_case_baseline: dict[str, float],
) -> Goal | None:
    """Render one slot's factor(s) and return its validated Goal.

    Most metrics are single-factor. A metric with a MetricRegistry.second_factor
    (currently only Cycle Time → Median Cycle Time) renders a second threshold row
    plus a weight slider and returns a two-factor Goal whose score is the weighted
    sum of the two factors' scores (see analysis.rank). The whole slot is dropped
    (None) if either factor's thresholds cannot score coherently.
    """
    primary = _configure_factor(
        target_cell, baseline_cell, worst_cell, metric, per_case_baseline
    )
    second_metric = MetricRegistry.second_factor(metric)
    if second_metric is None:
        return primary
    # Second factor: its own threshold row (same 4-col layout, so the header
    # still applies) + a weight slider splitting the two factors' scores.
    label_cell, sub_target, sub_baseline, sub_worst = st.columns(ROW_LAYOUT)
    label_cell.caption(f"↳ {second_metric.per_case_compact_label}")
    secondary = _configure_factor(
        sub_target, sub_baseline, sub_worst, second_metric, per_case_baseline
    )
    weight_label, weight_cell = st.columns([1, 3])
    weight_label.caption("↳ weight")
    weight = _weight_input(weight_cell, metric.per_case_column)
    weight_cell.caption(f"{weight:.0%} mean · {1 - weight:.0%} median")
    if primary is None or secondary is None:
        return None
    return Goal(
        metric=primary.metric,
        target=primary.target,
        baseline_ref=primary.baseline_ref,
        worst=primary.worst,
        secondary=secondary,
        weight=weight,
    )


def configure_goals(per_case_baseline: dict[str, float] | None) -> GoalConfig:
    """Render the goals block (count, metric per slot, editable thresholds).

    per_case_baseline is the resolved per-case baseline (real or demo
    constants), or None in real mode before the first run / when every
    baseline replication failed — then only the metric pickers render and no
    goals are scorable. Panel 3's "3 · Goals" header is rendered by app.py, like
    every sibling component's header.
    """
    if per_case_baseline is None:
        st.caption(
            f"Thresholds unlock once a run provides a baseline "
            f"(defaults: baseline ±{GOAL_IMPROVEMENT_PCT} %)."
        )
    else:
        st.caption(
            f"Score: 100 at target, 50 at baseline, 0 at worst. "
            f"Defaults: baseline ±{GOAL_IMPROVEMENT_PCT} %."
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

    if per_case_baseline is not None:
        header = st.columns(ROW_LAYOUT)
        header[0].caption("Goal")
        header[1].caption("Target (100)")
        header[2].caption("Baseline (50)")
        header[3].caption("Worst (0)")

    chosen_metrics: list[Metric] = []
    scorable_goals: list[Goal] = []
    for slot in range(goal_count):
        available = [
            metric for metric in rankable_metrics if metric not in chosen_metrics
        ]
        slot_key = _metric_slot_key(slot)
        # Reset a slot whose stored metric was just claimed by an earlier slot.
        if st.session_state.get(slot_key) not in available:
            st.session_state[slot_key] = available[0]
        if per_case_baseline is None:
            chosen_metrics.append(_metric_picker(st, slot, available))
            continue
        picker_cell, target_cell, baseline_cell, worst_cell = st.columns(ROW_LAYOUT)
        metric = _metric_picker(picker_cell, slot, available)
        chosen_metrics.append(metric)
        slot_goal = _configure_slot_goal(
            target_cell, baseline_cell, worst_cell, metric, per_case_baseline
        )
        if slot_goal is not None:
            scorable_goals.append(slot_goal)

    if per_case_baseline is not None:
        st.button(
            "Reset thresholds to defaults",
            key="goal_thresholds_reset",
            disabled=not st.session_state.goal_threshold_overrides,
            on_click=reset_goal_thresholds,
        )

    return GoalConfig(metrics=chosen_metrics, scorable_goals=scorable_goals)
