"""Interactive execution panel (Panel 4) — run/cancel controls and progress polling.

Part of ui/interactive/, so this module renders st.* widgets directly. Progress
polling lives in the module-level _render_run_progress fragment, driven by a
`run_every` timer so its reruns are fragment-scoped (only the progress bar
re-renders — no full-page flicker, mirroring discovery_panel); render_execution_panel
is a plain renderer that delegates to it only while a run is in flight, so the
timer never ticks when idle. Consumes
ui/services/run_manager (a ui/interactive -> ui/services dependency) for the
background-thread lifecycle, and calls core.demo.run_experiment /
core.orchestrator.run_experiment directly to launch a run — a "smart" component,
like resource_selector and factor_levels before it. Has no pure surface, so it is
exercised manually like app.py rather than unit-tested.

The Streamlit rerun/threading discipline (CLAUDE.md §6, the Streamlit threading
rules) applies here more than in any other component: session-state-derived
values (bpmn/json paths, log name) are snapshotted into locals before the
background thread starts, and the thread itself never touches st.session_state
or calls st.* — it communicates solely through the RunState object in
ui/services/run_manager.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from core import demo, orchestrator
from core.orchestrator import ExperimentResult
from core.parameters import Scenario
from core.simulation import store
from core.transformations import Transformation
from ui.services.run_manager import (
    cancel_experiment,
    clear_results,
    clear_run,
    commit_result,
    current_run,
    is_cancelling,
    start_experiment,
)


_POLL_SECONDS = 0.5  # progress-poll cadence; run_every reruns only this fragment


@st.fragment(run_every=_POLL_SECONDS)
def _render_run_progress(ss: Any, n_reps: int) -> None:
    """Poll the in-flight run; commit on success, toast + clear on any terminal outcome.

    The run_every timer re-runs only this fragment (fragment-scoped — no full-page
    flicker, and no app-scoped st.rerun() storm to swallow the Cancel click, which
    lives in the parent renderer). render_execution_panel calls this only while a run
    is in flight, so the timer never ticks when idle. Mirrors discovery_panel.
    """
    run_state = current_run(ss)
    if run_state is None or run_state.kind != "experiment":
        return  # defensive — the panel only calls this for its own kind
    progress = run_state.done / run_state.total if run_state.total > 0 else 0.0
    if is_cancelling(ss):
        text = "Cancelling — stopping running simulations…"
    else:
        text = f"Scenario {run_state.label} · rep {run_state.rep + 1}/{n_reps}"
    st.progress(progress, text=text)
    if run_state.outcome is None:
        return  # still running; the run_every timer re-polls (no sleep, no app rerun)
    if run_state.outcome.cancelled:
        st.toast("Run cancelled.", icon="⚠️")
    elif run_state.outcome.error is not None:
        # Persist to a durable key (main thread — the worker must never touch ss);
        # app.py renders it in the results slot. A toast would vanish before the
        # user could read a multi-line failure. clear_run below does NOT clear
        # experiment_error — clear_results (next run start) does.
        ss.experiment_error = run_state.outcome.error
    else:
        # Not cancelled and no error → result is set (RunOutcome invariant), and
        # the kind guard above makes it this panel's species.
        assert isinstance(run_state.outcome.result, ExperimentResult)
        commit_result(ss, run_state.outcome.result)
        st.toast(f"Completed {run_state.total} simulations.", icon="✅")
    clear_run(ss)
    st.rerun(scope="app")  # full rerun: show results panel; also stops the timer


def render_execution_panel(
    ss: Any,
    array_name: str,
    scenarios: list[Scenario],
    n_reps: int,
    n_cases: int,
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

    title is the caller-supplied section heading (e.g. "4 · Execution") — this
    component has no opinion on its position in the page layout, only on how the
    heading row is laid out alongside the run/cancel button.
    """
    total_runs = len(scenarios) * n_reps
    # The real pipeline also runs the 0%-automation baseline once per rep.
    baseline_note = "" if demo_mode else f" + {n_reps} baseline"
    with st.container(border=True):
        left, right = st.columns([3, 1])
        left.markdown(
            f"##### {title}  "
            f"<span style='background:#eef2ff;color:#3b6cf2;font-size:11px;"
            f"padding:2px 8px;border-radius:10px'>{array_name} · "
            f"{len(scenarios)} scenarios × {n_reps} reps = {total_runs} runs"
            f"{baseline_note} · {n_cases} cases/rep</span>",
            unsafe_allow_html=True,
        )
        if demo_mode:
            st.caption(
                "🧪 Demo run — results are illustrative (synthetic), not a real simulation."
            )

        run_state = current_run(ss)
        if run_state is not None and run_state.kind != "experiment":
            # Mutually exclusive runs — see RunState.kind's docstring; this
            # panel only waits.
            right.button(
                "▶ Run all scenarios",
                type="primary",
                use_container_width=True,
                disabled=True,
            )
            st.caption(
                "⏳ An as-discovered simulation is running — wait for it to "
                "finish (or cancel it in the Model fidelity tab)."
            )
        elif run_state is not None:
            if is_cancelling(ss):
                # Disabled + instant: rendered on the rerun the Cancel click triggers
                # below (not the fragment's 0.5s poll), so feedback is immediate and a
                # second click can't re-fire while the subprocess kill is in flight.
                right.button("⏳ Cancelling…", use_container_width=True, disabled=True)
            elif right.button("✕ Cancel", use_container_width=True):
                cancel_experiment(ss)
                st.rerun()  # swap to the disabled "Cancelling…" button immediately
            _render_run_progress(ss, n_reps)
        else:
            if right.button(
                "▶ Run all scenarios", type="primary", use_container_width=True
            ):
                if not demo_mode and ss.log is None:
                    st.error("No discovered model — upload a log first.")
                    st.stop()

                if demo_mode:

                    def experiment_fn(progress_cb, stop_ev):
                        return demo.run_experiment(
                            scenarios,
                            n_reps,
                            n_cases,
                            progress_cb,
                            bot_cost_per_hour=bot_cost_per_hour,
                            stop_event=stop_ev,
                        )
                else:
                    # Snapshot ss-derived values into locals before the thread
                    # starts (§6 threading rules). Function parameters need no
                    # snapshot — they are already call-time-frozen locals.
                    experiment_dir = store.new_experiment(ss.log.log_name)
                    bpmn_path = ss.log.bpmn_path
                    json_path = ss.log.json_path

                    def experiment_fn(progress_cb, stop_ev):
                        return orchestrator.run_experiment(
                            transformation=transformation,
                            bpmn_path=bpmn_path,
                            json_path=json_path,
                            target_activity=target,
                            scenarios=scenarios,
                            n_reps=n_reps,
                            n_cases=n_cases,
                            experiment_dir=experiment_dir,
                            on_progress=progress_cb,
                            selected_resource_id=selected_resource_id,
                            bot_cost_per_hour=bot_cost_per_hour,
                            stop_event=stop_ev,
                            max_workers=max_workers,
                        )

                clear_results(ss)
                start_experiment(ss, experiment_fn)
                st.rerun()  # one-shot app rerun: switches to the progress view
