"""Interactive model-fidelity panel — the as-discovered simulation and its
comparison against the uploaded log.

Part of ui/interactive/, so this module renders st.* widgets directly. It is
the second consumer of the shared run lifecycle in ui/run_manager (kind
"as_discovered"; the execution panel owns "experiment") and mirrors
execution_panel's shape: a module-level polling fragment, the §6 threading
discipline (session-state snapshots into locals before the thread starts), and
run/cancel controls. The two run kinds are mutually exclusive — each panel
disables its Run button while the other kind is in flight.

Vocabulary (load-bearing, CLAUDE.md §8): the as-discovered run simulates
Simod's model exactly as discovered — untransformed, patternless. It is NOT
the baseline (the transformed 0%-automation experiment reference). Has no pure
surface — its display prep lives in ui/table.py — so it is exercised manually
like app.py.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import streamlit as st

from core import analysis, orchestrator
from core.orchestrator import AsDiscoveredResult
from core.simulation import store
from ui.run_manager import (
    cancel_experiment,
    clear_as_discovered,
    clear_run,
    commit_as_discovered,
    current_run,
    is_cancelling,
    start_experiment,
)
from ui.table import prepare_fidelity_display, prepare_replication_display
from ui.interactive.error_surface import render_failure


_POLL_SECONDS = 0.5  # progress-poll cadence; run_every reruns only this fragment


@st.fragment(run_every=_POLL_SECONDS)
def _render_fidelity_progress(ss: Any) -> None:
    """Poll the in-flight as-discovered run; commit / persist on terminal outcome.

    Mirrors execution_panel._render_run_progress: fragment-scoped timer reruns,
    called only while a run of this panel's kind is in flight, one app-scoped
    rerun per terminal outcome.
    """
    run_state = current_run(ss)
    if run_state is None or run_state.kind != "as_discovered":
        return  # defensive — the panel only calls this for its own kind
    progress = run_state.done / run_state.total if run_state.total > 0 else 0.0
    if is_cancelling(ss):
        text = "Cancelling — stopping running simulations…"
    else:
        text = f"Replication {run_state.done}/{run_state.total}"
    st.progress(progress, text=text)
    if run_state.outcome is None:
        return  # still running; the run_every timer re-polls
    if run_state.outcome.cancelled:
        st.toast("As-discovered run cancelled.", icon="⚠️")
    elif run_state.outcome.error is not None:
        # Persist to the durable key (main thread — the worker never touches
        # ss); rendered below the controls on the full rerun.
        ss.as_discovered_error = run_state.outcome.error
    else:
        # Not cancelled and no error → result is set (RunOutcome invariant),
        # and the kind guard above makes it this panel's species.
        assert isinstance(run_state.outcome.result, AsDiscoveredResult)
        commit_as_discovered(ss, run_state.outcome.result)
        st.toast(f"Completed {run_state.total} as-discovered replications.", icon="✅")
    clear_run(ss)
    st.rerun(scope="app")


def _render_controls(ss: Any, n_reps: int, max_workers: int) -> None:
    """The fidelity toggle, the (pinned or free) case count, and run/cancel."""
    fidelity_available = ss.log_case_count is not None and ss.simod_csv_path is not None
    fidelity_on = st.toggle(
        "Fidelity check — compare against the uploaded log",
        value=fidelity_available,
        disabled=not fidelity_available,
        key=f"ad_fidelity_on_{ss.log_case_count}",
        help="Compares the simulated statistics against the same statistics "
        "computed from the uploaded log (one clock: first task start → last "
        "task end). Off: free exploration at any case count, no comparison.",
    )
    if fidelity_on:
        n_cases = int(ss.log_case_count)
        st.caption(
            f"Cases per replication: **{n_cases}** — pinned to the log's case "
            "count. Sampling noise scales with the case count, so model and "
            "log are only comparable at equal case counts."
        )
    else:
        n_cases = int(
            st.number_input(
                "Cases per replication",
                min_value=1,
                value=int(ss.log_case_count or 1000),
                step=100,
                key=f"ad_n_cases_{ss.log_case_count}",
            )
        )

    run_state = current_run(ss)
    if run_state is not None and run_state.kind != "as_discovered":
        # Mutually exclusive runs — see execution_panel's mirror guard.
        st.button("▶ Run as-discovered simulation", type="primary", disabled=True)
        st.caption(
            "⏳ An experiment run is in flight — wait for it to finish (or "
            "cancel it in the Experiment tab's Execution panel)."
        )
    elif run_state is not None:
        if is_cancelling(ss):
            st.button("⏳ Cancelling…", disabled=True)
        elif st.button("✕ Cancel"):
            cancel_experiment(ss)
            st.rerun()
        _render_fidelity_progress(ss)
    else:
        st.caption(
            f"{n_reps} replications × {n_cases} cases — replications and "
            "parallel workers follow the sidebar run config."
        )
        if st.button("▶ Run as-discovered simulation", type="primary"):
            # Snapshot ss-derived values into locals before the thread starts
            # (§6 threading rules).
            bpmn_path = ss.bpmn_path
            json_path = ss.json_path
            log_csv = ss.simod_csv_path if fidelity_on else None
            experiment_dir = store.new_experiment(
                f"{ss.log_name or 'run'}-as-discovered"
            )

            def fidelity_fn(progress_cb, stop_ev):
                return orchestrator.run_as_discovered(
                    bpmn_path=bpmn_path,
                    json_path=json_path,
                    n_reps=n_reps,
                    n_cases=n_cases,
                    experiment_dir=experiment_dir,
                    log_csv=log_csv,
                    on_progress=progress_cb,
                    stop_event=stop_ev,
                    max_workers=max_workers,
                )

            clear_as_discovered(ss)
            start_experiment(ss, fidelity_fn, kind="as_discovered")
            st.rerun()  # one-shot app rerun: switches to the progress view


def _render_results(ss: Any, result: AsDiscoveredResult) -> None:
    n_achieved = len(result.results)
    if result.failed_replications:
        st.warning(
            f"{len(result.failed_replications)} replication(s) failed and were "
            f"excluded — statistics summarise the {n_achieved} that completed.",
            icon="⚠️",
        )

    st.markdown("###### Simulated statistics per replication")
    per_rep = prepare_replication_display(result.results)
    st.dataframe(per_rep, use_container_width=True, hide_index=True)

    if result.observed is not None:
        st.markdown("###### Fidelity comparison")
        st.caption(
            f"Log (observed) is computed from the Simod-ready CSV of the "
            f"uploaded log; Model summarises {n_achieved} replications at "
            f"{result.n_cases} cases each (the log's own case count). "
            "Δ = Model − Log."
        )
        comparison = analysis.fidelity_table(
            dataclasses.asdict(result.observed), result.results
        )
        st.dataframe(
            prepare_fidelity_display(comparison, n_achieved),
            use_container_width=True,
            hide_index=True,
        )
        log_path = ss.log_path
        if log_path is not None and log_path.suffix.lower() == ".xes":
            st.caption(
                "⚠️ XES uploads reach the pipeline with no start timestamps — "
                "the converter synthesizes each case's first start (= its "
                "first end), so the observed clock runs slightly short and a "
                "small systematic positive Δ on the cycle rows is expected."
            )

    col_stats, col_logs = st.columns(2)
    col_stats.download_button(
        "⬇ Statistics (CSV)",
        per_rep.to_csv(index=False),
        file_name="as_discovered_statistics.csv",
        mime="text/csv",
        use_container_width=True,
    )
    col_logs.download_button(
        "⬇ Event logs (ZIP)",
        data=store.as_discovered_logs_zip(result.log_paths),
        file_name="as_discovered_event_logs.zip",
        mime="application/zip",
        use_container_width=True,
    )


def render_fidelity_panel(
    ss: Any, n_reps: int, max_workers: int, demo_mode: bool
) -> None:
    """Render the Model-fidelity tab's contents.

    Deliberately outside the experiment pipeline's panel numbering: this is a
    trust flow about the discovered model, not a stage of the experiment.
    """
    with st.container(border=True):
        st.markdown("##### Model fidelity — as-discovered simulation")
        if demo_mode:
            st.caption(
                "🧪 Unavailable in demo mode — the as-discovered simulation "
                "runs real Prosimos replications of the discovered model "
                "(untransformed, no automation pattern) and compares them "
                "against the uploaded log."
            )
            return
        st.caption(
            "Simulates the discovered model exactly as Simod produced it — no "
            "automation pattern, no factors — to check how faithfully it "
            "reproduces the uploaded log before you trust experiment results."
        )
        _render_controls(ss, n_reps, max_workers)
        if ss.as_discovered_error is not None:
            render_failure(
                f"As-discovered run failed.\n\n{ss.as_discovered_error}",
                ss.as_discovered_error,
                expander_label="Run output (log tail)",
                icon="❌",
            )
        if ss.as_discovered_result is not None:
            _render_results(ss, ss.as_discovered_result)
