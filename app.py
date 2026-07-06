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
from core.goals import GOAL_IMPROVEMENT_PCT
from core.metrics import Metric, MetricRegistry
from core.simulation import runner, store
from core.transformations import REGISTRY

from ui.run_manager import cancel_experiment, clear_results
from ui.interactive.resource_selector import select_resource
from ui.interactive.factor_levels import configure_factor_levels
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
ss.setdefault(
    "baseline_log_paths", {}
)  # n_cases -> list[Path], one log per replication
ss.setdefault("array_name", None)
ss.setdefault("scenarios", [])
ss.setdefault("baseline_agg", None)
ss.setdefault("failed_replications", [])


def _clear_log() -> None:
    clear_results(ss)
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

    uploaded = st.file_uploader("Event log (XES or CSV)", type=["xes", "csv"])
    use_sample = st.button(
        "Use sample log", use_container_width=True, disabled=not demo_mode
    )

    # Fingerprint the upload so we only discover ONCE per unique file.
    # CRITICAL: Streamlit reruns the script top-to-bottom on every interaction,
    # even while a slow synchronous subprocess is mid-flight. To prevent
    # launching concurrent Simod processes we set the fingerprint BEFORE the
    # subprocess call (so concurrent reruns short-circuit immediately) and
    # also hold a per-session "discovering" lock.
    upload_fp = (uploaded.name, uploaded.size) if uploaded else None
    already_discovered = ss.get("log_fingerprint") == upload_fp and ss.activities
    discovering = ss.get("discovering", False)

    needs_discovery = (uploaded and not already_discovered and not discovering) or (
        use_sample and demo_mode and not ss.activities
    )

    if discovering and uploaded:
        st.warning("Simod discovery is already running. Wait or click **Cancel**.")
        if st.button("Cancel discovery"):
            ss.discovering = False
            ss.log_fingerprint = None
            st.rerun()
        st.stop()

    if needs_discovery:
        # Claim the lock + fingerprint NOW, so any concurrent rerun short-circuits.
        ss.discovering = True
        ss.log_fingerprint = upload_fp
        if demo_mode:
            # Use the pre-baked demo model so the real activity-list +
            # factor-prepopulation path runs (only the simulation is synthetic).
            ss.log_name = "LoanApp (demo)"
            ss.bpmn_path, ss.json_path = demo.DEMO_BPMN, demo.DEMO_JSON
            ss.activities = list_activities(ss.bpmn_path)
            ss.discovering = False
        else:
            # Non-demo discovery is only reached via needs_discovery's first
            # disjunct, which requires a truthy upload (demo_mode is False here).
            assert uploaded is not None
            if not preflight_ok:
                ss.discovering = False
                ss.log_fingerprint = None
                st.error("Fix the preflight items above first.")
                st.stop()
            run_dir = store.new_experiment(uploaded.name)
            log_path = run_dir / uploaded.name
            log_path.write_bytes(uploaded.getbuffer())
            with st.status(
                "Running Simod discovery (~2 min for 100k events)…", expanded=True
            ) as s:
                try:
                    bpmn, params_path = runner.discover(
                        log_path,
                        run_dir,
                        java_home=java_home,
                        proc_log=store.discovery_log(run_dir),
                    )
                    ss.bpmn_path, ss.json_path = bpmn, params_path
                    ss.activities = list_activities(bpmn)
                    ss.log_name, ss.log_path = uploaded.name, log_path
                    s.update(
                        label=f"Discovered {len(ss.activities)} activities",
                        state="complete",
                    )
                except Exception as e:
                    ss.log_fingerprint = None
                    s.update(label="Simod failed", state="error")
                    st.exception(e)
                    ss.discovering = False
                    st.stop()
                finally:
                    ss.discovering = False
        st.rerun()

    if ss.log_name:
        st.caption(f"📄 Loaded: **{ss.log_name}** · {len(ss.activities)} activities")
        if st.button("Reset log", use_container_width=True):
            cancel_experiment(ss)
            _clear_log()
            st.rerun()

    _goal_specs: list[Metric] = []
    if ss.activities:
        st.divider()
        st.subheader("Goals")
        st.caption(
            f"Scoring: 100 = target (±{GOAL_IMPROVEMENT_PCT} % vs baseline), "
            f"50 = baseline, 0 = worst"
        )
        _n_goals = st.radio(
            "Goals",
            list(range(1, len(MetricRegistry.rankable()) + 1)),
            index=0,
            horizontal=True,
            key="goal_count",
            label_visibility="collapsed",
        )

        _chosen: list[Metric] = []
        for _i in range(_n_goals):
            _avail = [m for m in MetricRegistry.rankable() if m not in _chosen]
            _k = f"goal_metric_{_i}"
            if ss.get(_k) not in _avail:
                ss[_k] = _avail[0]
            _m = st.selectbox(
                f"Goal {_i + 1}",
                options=_avail,
                format_func=lambda m: m.per_case_display_name,
                key=_k,
                label_visibility="collapsed",
            )
            _chosen.append(_m)
            _goal_specs.append(_m)

    st.divider()
    st.subheader("Run config")
    n_reps = st.number_input("Replications (N)", 1, 100, 5)
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

        pattern_id = st.selectbox(
            "Substitution pattern",
            list(REGISTRY.keys()),
            format_func=lambda k: REGISTRY[k].label,
        )

with col2:
    with st.container(border=True):
        st.markdown("##### 2 · Factor levels")
        transformation = REGISTRY[pattern_id]
        parameters = configure_factor_levels(
            transformation,
            target,
            prosimos_data,
            _task_id,
            selected_pool_size,
            frozen_pool_size,
        )

# --- Design + execution panel ------------------------------------------------
array_name, scenarios = build_scenarios(parameters, transformation.id, target)
ss.array_name, ss.scenarios = array_name, scenarios

render_execution_panel(
    ss,
    array_name,
    scenarios,
    n_reps,
    demo_mode,
    target,
    transformation,
    selected_resource_id,
    bot_cost_per_hour,
    max_workers,
    title="3 · Execution",
)

# --- Results panel -----------------------------------------------------------
if ss.results is not None:
    agg = analysis.aggregate(ss.results)

    with st.container(border=True):
        st.markdown("##### 4 · Ranked scenarios")
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
                "Cost goals are marked unmet.",
                icon="⚠️",
            )
        ranked = render_ranked_scenarios(
            agg, _goal_specs, parameters, ss.baseline_agg, demo_mode
        )
        st.markdown("###### Main effects")
        render_main_effects(ss.results, parameters)

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

        if json_paths:
            st.markdown("###### Scenario parameters (params.json)")
            sel = st.selectbox(
                "Scenario",
                sorted(json_paths),
                key="params_sel",
                format_func=lambda s: f"Scenario {s}",
            )
            if sel:
                with st.expander("View params.json"):
                    st.json(json_paths[sel].read_text())

        st.markdown("###### Export")
        stats_csv = ranked.to_csv(index=False)
        col_bpmn, col_json, col_stats, col_logs, col_all = st.columns(5)
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
            file_name="statistics.csv",
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
            data=store.group_zip(bpmn_file, json_paths, stats_csv)
            if (bpmn_file and json_paths)
            else b"",
            file_name="model_bundle.zip",
            mime="application/zip",
            use_container_width=True,
            disabled=not (bpmn_file and json_paths),
        )

    baseline_agg = ss.get("baseline_agg")
    if baseline_agg is not None:
        with st.container(border=True):
            st.markdown("##### 5 · Baseline comparison")
            st.caption(
                "Total metrics averaged across replications. Δ values are relative to "
                "the 0%-automation baseline — the pattern with every case on the human "
                "path, at Simod-discovered durations and staffing."
            )
            st.dataframe(
                analysis.compare_to_baseline(agg, baseline_agg),
                use_container_width=True,
                hide_index=True,
            )
    elif not demo_mode:
        with st.container(border=True):
            st.markdown("##### 5 · Baseline comparison")
            st.warning(
                "All baseline replications failed — baseline comparison is unavailable. "
                "Check the run logs for details.",
                icon="⚠️",
            )
