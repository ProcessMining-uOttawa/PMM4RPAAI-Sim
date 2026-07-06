"""Interactive execution panel (Panel 3) — run/cancel controls and progress polling.

Part of ui/interactive/, so this module renders st.* widgets directly, and it owns
a Streamlit fragment: render_execution_panel is decorated with @st.fragment so
progress polling reruns only this panel, not the whole page. Consumes
ui/run_manager (a ui/interactive -> ui/ presentation-primitive dependency) for the
background-thread lifecycle, and calls core.demo.run_experiment /
core.orchestrator.run_experiment directly to launch a run — a "smart" component,
like resource_selector and factor_levels before it. Has no pure surface, so it is
exercised manually like app.py rather than unit-tested.

The Streamlit rerun/threading discipline (CLAUDE.md §6, the Streamlit threading
rules) applies here more than in any other component: session-state-derived
values (bpmn/json paths, log name) are snapshotted into locals before the
background thread starts, and the thread itself never touches st.session_state
or calls st.* — it communicates solely through the RunState object in
ui/run_manager.
"""

from __future__ import annotations

import time
from typing import Any

import streamlit as st

from core import demo, orchestrator
from core.parameters import Scenario
from core.simulation import store
from core.transformations import Transformation
from ui.run_manager import (
    cancel_experiment,
    clear_results,
    clear_run,
    commit_result,
    current_run,
    start_experiment,
)


@st.fragment
def render_execution_panel(
    ss: Any,
    array_name: str,
    scenarios: list[Scenario],
    n_reps: int,
    demo_mode: bool,
    target: str,
    transformation: Transformation,
    selected_resource_id: str | None,
    bot_cost_per_hour: float,
    max_workers: int,
    *,
    title: str,
) -> None:
    """Render the execution panel: run summary, run/cancel controls, and progress polling.

    title is the caller-supplied section heading (e.g. "3 · Execution") — this
    component has no opinion on its position in the page layout, only on how the
    heading row is laid out alongside the run/cancel button.
    """
    total_runs = len(scenarios) * n_reps
    with st.container(border=True):
        left, right = st.columns([3, 1])
        left.markdown(
            f"##### {title}  "
            f"<span style='background:#eef2ff;color:#3b6cf2;font-size:11px;"
            f"padding:2px 8px;border-radius:10px'>{array_name} · "
            f"{len(scenarios)} scenarios × {n_reps} reps = {total_runs} runs</span>",
            unsafe_allow_html=True,
        )
        if demo_mode:
            st.caption(
                "🧪 Demo run — results are illustrative (synthetic), not a real simulation."
            )

        run_state = current_run(ss)
        if run_state is not None:
            progress = run_state.done / run_state.total if run_state.total > 0 else 0.0
            st.progress(
                progress,
                text=f"Scenario {run_state.label} · rep {run_state.rep + 1}/{n_reps}",
            )
            if right.button("✕ Cancel", use_container_width=True):
                cancel_experiment(ss)

            if run_state.outcome is None:
                time.sleep(0.5)
                st.rerun()  # fragment-scoped: only this panel re-renders during polling
            else:
                if run_state.outcome.cancelled:
                    st.toast("Run cancelled.", icon="⚠️")
                elif run_state.outcome.error is not None:
                    st.toast(f"Simulation failed: {run_state.outcome.error}", icon="❌")
                else:
                    # Not cancelled and no error → result is set (RunOutcome invariant).
                    assert run_state.outcome.result is not None
                    commit_result(ss, run_state.outcome.result)
                    st.toast(f"Completed {total_runs} simulations.", icon="✅")
                clear_run(ss)
                st.rerun(scope="app")  # full rerun: the results panel needs to appear
        else:
            if right.button(
                "▶ Run all scenarios", type="primary", use_container_width=True
            ):
                if not demo_mode and (not ss.bpmn_path or not ss.json_path):
                    st.error("No discovered model — upload a log first.")
                    st.stop()

                if demo_mode:

                    def experiment_fn(progress_cb, stop_ev):
                        return demo.run_experiment(
                            scenarios,
                            n_reps,
                            progress_cb,
                            bot_cost_per_hour=bot_cost_per_hour,
                            stop_event=stop_ev,
                        )
                else:
                    # Snapshot ss-derived values into locals before the thread
                    # starts (§6 threading rules). Function parameters need no
                    # snapshot — they are already call-time-frozen locals.
                    experiment_dir = store.new_experiment(ss.log_name or "run")
                    bpmn_path = ss.bpmn_path
                    json_path = ss.json_path

                    def experiment_fn(progress_cb, stop_ev):
                        return orchestrator.run_experiment(
                            transformation=transformation,
                            bpmn_path=bpmn_path,
                            json_path=json_path,
                            target_activity=target,
                            scenarios=scenarios,
                            n_reps=n_reps,
                            experiment_dir=experiment_dir,
                            on_progress=progress_cb,
                            selected_resource_id=selected_resource_id,
                            bot_cost_per_hour=bot_cost_per_hour,
                            stop_event=stop_ev,
                            max_workers=max_workers,
                        )

                clear_results(ss)
                start_experiment(ss, experiment_fn)
                st.rerun()  # fragment-scoped: switches this panel to progress view
