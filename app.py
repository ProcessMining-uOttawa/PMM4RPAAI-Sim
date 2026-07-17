"""Streamlit dashboard — Mockup B layout."""

from __future__ import annotations
import json
import os
import xml.etree.ElementTree as ET
import streamlit as st

from pathlib import Path

from core import analysis, demo
from core.bpmn.query import find_task_by_name, list_activities
from core.simulation.prosimos.query import resource_selector_config
from core.constants import COL_MEAN_COST
from core.taguchi import build_scenarios
from core.goals import baseline_per_case
from core.simulation import runner, store
from core.transformations import REGISTRY

from ui.run_manager import cancel_experiment, clear_results
from ui.discovery_manager import (
    DiscoveryPhase,
    DiscoveryResult,
    clear_discovery,
    discovery_error,
    discovery_phase,
    start_discovery,
)
from ui.interactive.resource_selector import select_resource
from ui.interactive.factor_levels import configure_factor_levels
from ui.interactive.goal_config import (
    configure_goals,
    reset_goal_selection,
    reset_goal_thresholds,
)
from ui.interactive.discovery_panel import render_discovery_progress
from ui.interactive.main_effects import render_main_effects
from ui.interactive.ranked_scenarios import render_ranked_scenarios
from ui.interactive.simod_preflight import render_simod_preflight
from ui.interactive.execution_panel import render_execution_panel

st.set_page_config(
    page_title="Automation What-If Simulator", page_icon="⚙", layout="wide"
)


# --- session state defaults --------------------------------------------------
ss = st.session_state
ss.setdefault("log_name", None)
ss.setdefault("log_path", None)  # Path to uploaded log
ss.setdefault("activities", [])
ss.setdefault("bpmn_path", None)
ss.setdefault("json_path", None)
ss.setdefault("results", None)  # tidy per-replication DataFrame
ss.setdefault(
    "experiment_bpmn_path", None
)  # single transformed BPMN, shared across scenarios
ss.setdefault("scenario_json_paths", {})  # sid -> Path, one params.json per scenario
ss.setdefault("scenario_log_paths", {})  # sid -> list[Path], one log per replication
ss.setdefault("baseline_log_paths", [])  # one log per baseline replication
ss.setdefault("run_n_cases", None)  # cases/rep the committed run executed at
ss.setdefault("array_name", None)
ss.setdefault("scenarios", [])
ss.setdefault("baseline_agg", None)
ss.setdefault("failed_replications", [])
# indicator-column -> {"target"/"worst"/"weight": edited value}, plus the
# generation counter embedded in the goal widget keys. goal_indicator_selection:
# default-indicator column -> chosen extra-indicator columns. Both are log-level
# state (absolute thresholds and indicator choices are meaningless against a
# different process): reset via _clear_process_state() when the log changes,
# never by clear_results(), which runs at every run start.
ss.setdefault("goal_threshold_overrides", {})
ss.setdefault("goal_threshold_reset_generation", 0)
ss.setdefault("goal_indicator_selection", {})


def _clear_process_state() -> None:
    """Clear everything derived from the currently loaded process.

    Cancels any in-flight run (its commit would land in the wrong session),
    abandons any in-flight discovery, drops its results, the baseline
    (log-scoped — clear_results deliberately keeps it), the goal thresholds, and
    the indicator selection.
    Called when the log is reset or replaced — the two events after which this
    state would describe a different process.
    """
    cancel_experiment(ss)
    clear_discovery(ss)
    clear_results(ss)
    ss.baseline_agg = None
    reset_goal_thresholds()
    reset_goal_selection()


def _clear_log() -> None:
    _clear_process_state()
    ss.log_name = None
    ss.log_path = None
    ss.activities = []
    ss.bpmn_path = None
    ss.json_path = None
    ss.log_fingerprint = None


# --- header ------------------------------------------------------------------
st.markdown(
    "<h2 style='margin-bottom:0'>⚙ Automation What-If Simulator</h2>"
    f"<div style='color:#6b7280;font-size:13px;margin-bottom:14px'>"
    f"{ss.log_name or 'No log loaded'} · "
    f"{len(ss.activities)} activities discovered</div>",
    unsafe_allow_html=True,
)

# --- sidebar: experiment state ----------------------------------------------
with st.sidebar:
    st.subheader("Experiment")
    demo_mode = st.toggle(
        "Demo mode (no Simod/Prosimos)",
        value=True,
        help="Uses synthetic discovery + simulation so you can "
        "click through the UI without external tools.",
    )

    preflight_ok, java_home = render_simod_preflight(demo_mode)

    uploaded = st.file_uploader(
        "Event log (XES or CSV)", type=["xes", "csv"], disabled=demo_mode
    )
    use_sample = st.button(
        "Use sample log", use_container_width=True, disabled=not demo_mode
    )
    # Demo discovery loads the pre-baked model, so an uploaded log is never used.
    # Treat it as absent — the uploader is disabled above, but a file uploaded
    # before toggling demo on would otherwise linger in the widget and drive the
    # fingerprint / discovery logic (tying log_fingerprint to an ignored upload).
    if demo_mode:
        uploaded = None

    # Discovery is an explicit state machine keyed by the upload fingerprint
    # (ui/discovery_manager). Real discovery runs in a background thread — see §6,
    # the interrupt corollary — so a mid-discovery rerun can't abort it; the
    # sidebar routes on discovery_phase() for the file currently in the uploader.
    upload_fp = (uploaded.name, uploaded.size) if uploaded else None
    already_discovered = ss.get("log_fingerprint") == upload_fp and ss.activities
    phase = discovery_phase(ss, upload_fp)

    # RUNNING → poll via the fragment and hide the rest of the sidebar until it
    # finishes (the fragment triggers a full app rerun on completion). Because
    # discovery runs off-thread, a run-config nudge here just re-renders this
    # progress view instead of interrupting Simod.
    if phase is DiscoveryPhase.RUNNING:
        render_discovery_progress(ss)
        st.stop()

    # FAILED / CANCELLED → show the outcome and offer retry; don't auto-restart.
    # A different upload makes this session irrelevant (phase becomes None), so
    # the banner can never persist across a log change.
    if phase in (DiscoveryPhase.FAILED, DiscoveryPhase.CANCELLED):
        if phase is DiscoveryPhase.FAILED:
            error = discovery_error(ss)
            assert error is not None  # phase FAILED ⇒ outcome.error set
            st.error("Simod discovery failed.")
            st.exception(error)
        else:
            st.info("Discovery cancelled.")
        if st.button("Retry discovery"):
            clear_discovery(ss)  # back to idle → the block below re-discovers
            st.rerun()
        st.stop()

    needs_discovery = (uploaded and not already_discovered) or (
        use_sample and demo_mode and not ss.activities
    )

    if needs_discovery:
        # Fingerprint now so a concurrent rerun sees already_discovered and
        # short-circuits. Replacing the log without "Reset log" must not carry
        # over state from the previous process; the remaining log-level keys are
        # assigned fresh values below.
        ss.log_fingerprint = upload_fp
        _clear_process_state()
        if demo_mode:
            # Pre-baked model, no subprocess — instant, so stay synchronous.
            # The real activity-list + factor-prepopulation path still runs
            # (only the simulation is synthetic).
            ss.log_name = "LoanApp (demo)"
            ss.bpmn_path, ss.json_path = demo.DEMO_BPMN, demo.DEMO_JSON
            ss.activities = list_activities(ss.bpmn_path)
            st.rerun()
        else:
            # Non-demo discovery is only reached via needs_discovery's first
            # disjunct, which requires a truthy upload (demo_mode is False here).
            assert uploaded is not None and upload_fp is not None
            if not preflight_ok:
                ss.log_fingerprint = None
                st.error("Fix the preflight items above first.")
                st.stop()
            run_dir = store.new_experiment(uploaded.name)
            log_path = run_dir / uploaded.name
            log_path.write_bytes(uploaded.getbuffer())
            # Snapshot everything the worker needs into locals before the thread
            # starts — it must not touch ss or st.* (§6 threading rules).
            log_name = uploaded.name
            proc_log = store.discovery_log(run_dir)

            def discover_fn() -> DiscoveryResult:
                bpmn, params_path = runner.discover(
                    log_path, run_dir, java_home=java_home, proc_log=proc_log
                )
                return DiscoveryResult(
                    bpmn_path=bpmn,
                    json_path=params_path,
                    activities=list_activities(bpmn),
                    log_name=log_name,
                    log_path=log_path,
                )

            start_discovery(ss, upload_fp, discover_fn)
            st.rerun()

    if ss.log_name:
        st.caption(f"📄 Loaded: **{ss.log_name}** · {len(ss.activities)} activities")
        if st.button("Reset log", use_container_width=True):
            _clear_log()
            st.rerun()

    st.divider()
    st.subheader("Run config")
    n_reps = st.number_input("Replications (N)", 1, 100, 5)
    n_cases = st.number_input(
        "Cases per replication",
        min_value=1,
        value=1000,
        step=100,
        help="How many cases each Prosimos replication simulates. Applies uniformly "
        "to every scenario and the baseline.",
    )
    max_workers = st.number_input(
        "Parallel workers",
        min_value=1,
        max_value=os.cpu_count() or 1,
        value=os.cpu_count() or 1,
        step=1,
        help="Number of Prosimos simulations to run in parallel. Higher values use more CPU.",
    )
    bot_cost_per_hour = st.number_input(
        "Bot cost ($/hr)", min_value=0.0, value=0.0, step=1.0
    )

# --- gate: need a log first --------------------------------------------------
if not ss.activities:
    st.info("Upload a log or click **Use sample log** in the sidebar to begin.")
    st.stop()

# Resolved per-case baseline for goal thresholds and scoring. Real baseline when
# one exists; demo constants in demo mode (demo runs commit baseline_agg=None);
# None in real mode before the first run or when every baseline replication
# failed. baseline_agg survives run start (log-scoped — see clear_results), so
# Panel 3's threshold rows stay stable while a re-run is in flight.
if ss.baseline_agg is not None:
    per_case_baseline: dict[str, float] | None = baseline_per_case(ss.baseline_agg)
elif demo_mode:
    per_case_baseline = baseline_per_case(demo.demo_baseline_agg())
else:
    per_case_baseline = None

# --- main: 2x2 dashboard -----------------------------------------------------
col1, col2 = st.columns(2)

with col1:
    with st.container(border=True):
        st.markdown("##### 1 · Activity & pattern")
        # Default to the 2nd activity (skip the typical start step), clamped so a
        # single-activity log doesn't raise an out-of-range StreamlitAPIException.
        target = st.selectbox(
            "Target activity", ss.activities, index=min(1, len(ss.activities) - 1)
        )

        # Load model info — results shared with col2 (duration prepopulation).
        _task_id: str | None = None
        prosimos_data: dict | None = None
        _resource_cfg = None
        # Runs in demo mode too — demo points bpmn_path/json_path at the demo model.
        if ss.bpmn_path and ss.json_path:
            try:
                _tree = ET.parse(str(ss.bpmn_path))
                _target_el = find_task_by_name(_tree, target)
                if _target_el is not None:
                    _task_id = _target_el.get("id")
                    prosimos_data = json.loads(Path(ss.json_path).read_text())
            except (ET.ParseError, json.JSONDecodeError, OSError):
                pass
            if _task_id is not None and prosimos_data is not None:
                _resource_cfg = resource_selector_config(prosimos_data, _task_id)

        # Resource selector — runs in demo mode too (demo points bpmn/json at the
        # pre-baked model). The interactive component renders a picker only when
        # the task exposes selectable or frozen resources; otherwise it returns an
        # empty selection (pools stay None, the no-info fallback).
        selected_resource_id: str | None = None
        selected_pool_size: int | None = None
        frozen_pool_size: int | None = None

        if _resource_cfg is not None and prosimos_data is not None:
            _selection = select_resource(_resource_cfg, prosimos_data)
            selected_resource_id = _selection.selected_resource_id
            selected_pool_size = _selection.selected_pool_size
            frozen_pool_size = _selection.frozen_pool_size

        # Single-pattern reality: XORSplitAutomation is the only registered
        # transformation and no second one will be added, so there is no picker —
        # just the sole registry entry, shown read-only so users stay oriented on
        # which intervention the simulation applies. The REGISTRY / Transformation
        # ABC abstraction is retained; re-add a selectbox here if that ever changes.
        transformation = next(iter(REGISTRY.values()))
        st.caption(f"Substitution pattern: {transformation.label}")

with col2:
    with st.container(border=True):
        st.markdown("##### 2 · Factor levels")
        parameters = configure_factor_levels(
            transformation,
            target,
            prosimos_data,
            _task_id,
            selected_pool_size,
            frozen_pool_size,
        )

# Goals span full width below Activity + Factor levels: each goal renders in
# its own tab, so the active goal's threshold grid gets the whole page width,
# and Panel 3's height swing (a few pickers pre-run → the active tab's grid
# post-run) grows the page vertically instead of unbalancing the top two
# columns. Panel-numbered by workflow order (design → score), so 3 · Goals
# reads after 2 · Factor levels.
with st.container(border=True):
    st.markdown("##### 3 · Goals")
    goal_config = configure_goals(per_case_baseline)

# --- Design + execution panel ------------------------------------------------
array_name, scenarios = build_scenarios(parameters, transformation.id, target)
ss.array_name, ss.scenarios = array_name, scenarios

render_execution_panel(
    ss,
    array_name,
    scenarios,
    n_reps,
    n_cases,
    demo_mode,
    target,
    transformation,
    selected_resource_id,
    bot_cost_per_hour,
    max_workers,
    title="4 · Execution",
)

# --- Results panel -----------------------------------------------------------
if ss.results is not None:
    agg = analysis.aggregate(ss.results)
    # Read here (before st.tabs) to decide whether the Baseline tab exists: real
    # mode always shows it (comparison table, or a warning if all baseline reps
    # failed); demo has no baseline, so the tab is omitted.
    baseline_agg = ss.get("baseline_agg")

    with st.container(border=True):
        st.markdown("##### 5 · Results")
        if demo_mode:
            st.info(
                "**Demo mode — illustrative results.** These metrics are synthetic "
                "(derived from the factor values, not a real Prosimos simulation). "
                "The discovered model and factor levels are real; only the outcomes "
                "are mocked.",
                icon="🧪",
            )
        if ss.failed_replications:
            st.warning(
                f"{len(ss.failed_replications)} replication(s) failed and were excluded from results. "
                "Results are based on the remaining successful replications. "
                "Check the run logs for details.",
                icon="⚠️",
            )
        if ss.results[COL_MEAN_COST].isna().any():
            st.warning(
                "Cost data is unavailable for one or more runs — Prosimos did not "
                "produce a stats CSV with a parseable 'Individual Task Statistics' section. "
                "Cost goals score 0 for the affected scenarios.",
                icon="⚠️",
            )
        # per_case_baseline is None here only in real mode (demo always
        # resolves constants).
        if per_case_baseline is None:
            st.error(
                "Goal scoring is unavailable — all baseline replications failed, so "
                "there are no real targets to score against. Re-run to restore goal "
                "rankings. Scenario KPIs, main effects, and exports below remain valid.",
                icon="🚫",
            )
        # Baseline is real-mode only (demo produces no baseline); in real mode it
        # is always shown — as a comparison table, or a warning if every baseline
        # replication failed. One boolean drives both the tab and its body.
        show_baseline = baseline_agg is not None or not demo_mode
        tab_labels = ["Ranking", "Main effects"]
        if show_baseline:
            tab_labels.append("Baseline")
        result_tabs = st.tabs(tab_labels)

        with result_tabs[0]:
            ranked = render_ranked_scenarios(
                agg,
                goal_config.metrics,
                goal_config.scorable_goals,
                goal_config.selected_extras,
                parameters,
            )
        with result_tabs[1]:
            render_main_effects(ss.results, parameters)
        if show_baseline:
            with result_tabs[-1]:
                if baseline_agg is not None:
                    # ss.run_n_cases, not the widget value: the caption describes the
                    # committed run, which the widget may have moved past since.
                    st.caption(
                        f"Total metrics averaged across replications, at {ss.run_n_cases} "
                        "cases per replication. Δ values are relative to the 0%-automation "
                        "baseline — the pattern with every case on the human path, at "
                        "Simod-discovered durations and staffing. Bot failures are "
                        "structurally zero in the baseline (no case reaches the bot), so "
                        "its Δ is the scenario's own count."
                    )
                    st.dataframe(
                        analysis.compare_to_baseline(agg, baseline_agg),
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.warning(
                        "All baseline replications failed — baseline comparison is unavailable. "
                        "Check the run logs for details.",
                        icon="⚠️",
                    )

        # Export row — below the tabs (still inside the results panel) because the
        # Statistics CSV needs `ranked` from the Ranking tab body above. Acts on
        # the whole result set, so it stays visible regardless of the active tab.
        _raw_bpmn_path = ss.get("experiment_bpmn_path")
        bpmn_file: Path | None = (
            Path(_raw_bpmn_path)
            if _raw_bpmn_path and Path(_raw_bpmn_path).exists()
            else None
        )
        json_paths = {
            sid: Path(p)
            for sid, p in ss.get("scenario_json_paths", {}).items()
            if Path(p).exists()
        }

        st.markdown("###### Export")
        stats_csv = ranked.to_csv(index=False)
        sn_csv = analysis.sn_export_table(ss.results, parameters).to_csv(index=False)
        # Downloaded files escape the illustrative-results banner, so in demo mode
        # the filename itself carries the synthetic-data label.
        _csv_suffix = "_demo" if demo_mode else ""
        col_bpmn, col_json, col_stats, col_sn, col_logs, col_all = st.columns(6)
        col_json.download_button(
            "⬇ Params (ZIP)",
            data=store.json_zip(json_paths),
            file_name="scenarios.zip",
            mime="application/zip",
            use_container_width=True,
            disabled=not json_paths,
        )
        col_stats.download_button(
            "⬇ Statistics (CSV)",
            stats_csv,
            file_name=f"statistics{_csv_suffix}.csv",
            mime="text/csv",
            use_container_width=True,
        )
        col_sn.download_button(
            "⬇ S/N (CSV)",
            sn_csv,
            file_name=f"signal_to_noise{_csv_suffix}.csv",
            mime="text/csv",
            use_container_width=True,
        )
        col_bpmn.download_button(
            "⬇ BPMN",
            data=bpmn_file.read_bytes() if bpmn_file else b"",
            file_name="model.bpmn",
            mime="application/xml",
            use_container_width=True,
            disabled=bpmn_file is None,
        )
        _slp = ss.scenario_log_paths
        _blp = ss.baseline_log_paths
        _has_logs = not demo_mode and bool(_slp or _blp)
        col_logs.download_button(
            "⬇ Event logs (ZIP)",
            data=store.event_logs_zip(_slp, _blp) if _has_logs else b"",
            file_name="event_logs.zip",
            mime="application/zip",
            use_container_width=True,
            disabled=not _has_logs,
        )
        col_all.download_button(
            "⬇ Model (ZIP)",
            data=store.group_zip(bpmn_file, json_paths, stats_csv, sn_csv)
            if (bpmn_file and json_paths)
            else b"",
            file_name="model_bundle.zip",
            mime="application/zip",
            use_container_width=True,
            disabled=not (bpmn_file and json_paths),
        )
