"""Streamlit dashboard — Mockup B layout."""

from __future__ import annotations
import json
import os
import time
import xml.etree.ElementTree as ET
import streamlit as st

from pathlib import Path

from core import analysis, demo, orchestrator
from core.bpmn.query import find_task_by_name, list_activities
from core.simulation.prosimos.query import resource_selector_config
from core.constants import COL_MEAN_COST
from core.taguchi import build_scenarios
from core.goals import Goal, GOAL_IMPROVEMENT_PCT, baseline_per_case
from core.metrics import Metric, MetricRegistry
from core.simulation import runner, store
from core.transformations import REGISTRY

from ui import preflight
from ui.plots import factor_label_map, main_effects_chart
from ui.run_manager import (
    start_experiment,
    cancel_experiment,
    clear_run,
    current_run,
    commit_result,
)
from ui.table import prepare_ranked_display
from ui.interactive.resource_selector import select_resource
from ui.interactive.factor_levels import render_factor_levels

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


def _clear_results() -> None:
    ss.results = None
    ss.experiment_bpmn_path = None
    ss.scenario_json_paths = {}
    ss.baseline_agg = None
    ss.scenario_log_paths = {}
    ss.baseline_log_paths = {}
    ss.failed_replications = []


def _clear_log() -> None:
    _clear_results()
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

    if not demo_mode:
        with st.expander("Simod preflight", expanded=True):
            checks, detected_java = preflight.run_checks()
            for c in checks:
                st.markdown(f"{'✅' if c.ok else '❌'} **{c.name}** — {c.detail}")
                if not c.ok and c.fix:
                    st.caption(c.fix)
            preflight_ok = preflight.all_ok(checks)
            java_home = (
                st.text_input(
                    "JAVA_HOME for Simod",
                    value=detected_java or "",
                    help="Used only for Simod's subprocess; leaves your system Java alone.",
                )
                or None
            )
    else:
        preflight_ok, java_home = True, None

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
            [1, 2, 3],
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
        max_value=os.cpu_count(),
        value=os.cpu_count(),
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
        params = render_factor_levels(
            transformation,
            target,
            prosimos_data,
            _task_id,
            selected_pool_size,
            frozen_pool_size,
        )

# --- Design + execution panel ------------------------------------------------
array_name, scenarios = build_scenarios(params, transformation.id, target)
ss.array_name, ss.scenarios = array_name, scenarios
total_runs = len(scenarios) * n_reps


@st.fragment
def _panel3() -> None:
    with st.container(border=True):
        left, right = st.columns([3, 1])
        left.markdown(
            f"##### 3 · Execution  "
            f"<span style='background:#eef2ff;color:#3b6cf2;font-size:11px;"
            f"padding:2px 8px;border-radius:10px'>{array_name} · "
            f"{len(scenarios)} scenarios × {n_reps} reps = {total_runs} runs</span>",
            unsafe_allow_html=True,
        )
        if demo_mode:
            st.caption(
                "🧪 Demo run — results are illustrative (synthetic), not a real simulation."
            )

        _rs = current_run(ss)
        if _rs is not None:
            _pct = _rs.done / _rs.total if _rs.total > 0 else 0.0
            st.progress(_pct, text=f"Scenario {_rs.label} · rep {_rs.rep + 1}/{n_reps}")
            if right.button("✕ Cancel", use_container_width=True):
                cancel_experiment(ss)

            if _rs.outcome is None:
                time.sleep(0.5)
                st.rerun()  # fragment-scoped: only Panel 3 re-renders during polling
            else:
                if _rs.outcome.cancelled:
                    st.toast("Run cancelled.", icon="⚠️")
                elif _rs.outcome.error is not None:
                    st.toast(f"Simulation failed: {_rs.outcome.error}", icon="❌")
                else:
                    # Not cancelled and no error → result is set (RunOutcome invariant).
                    assert _rs.outcome.result is not None
                    commit_result(ss, _rs.outcome.result)
                    st.toast(f"Completed {total_runs} simulations.", icon="✅")
                clear_run(ss)
                st.rerun(scope="app")  # full rerun: Panel 4 needs to appear
        else:
            if right.button(
                "▶ Run all scenarios", type="primary", use_container_width=True
            ):
                if not demo_mode and (not ss.bpmn_path or not ss.json_path):
                    st.error("No discovered model — upload a log first.")
                    st.stop()

                if demo_mode:

                    def _fn(progress_cb, stop_ev):
                        return demo.run_experiment(
                            scenarios,
                            n_reps,
                            progress_cb,
                            bot_cost_per_hour=bot_cost_per_hour,
                            stop_event=stop_ev,
                        )
                else:
                    _experiment_dir = store.new_experiment(ss.log_name or "run")
                    _bpmn_path = ss.bpmn_path
                    _json_path = ss.json_path
                    _target_activity = target
                    _selected_resource_id = selected_resource_id

                    def _fn(progress_cb, stop_ev):
                        return orchestrator.run_experiment(
                            transformation=transformation,
                            bpmn_path=_bpmn_path,
                            json_path=_json_path,
                            target_activity=_target_activity,
                            scenarios=scenarios,
                            n_reps=n_reps,
                            experiment_dir=_experiment_dir,
                            on_progress=progress_cb,
                            selected_resource_id=_selected_resource_id,
                            bot_cost_per_hour=bot_cost_per_hour,
                            stop_event=stop_ev,
                            max_workers=max_workers,
                        )

                _clear_results()
                start_experiment(ss, _fn)
                st.rerun()  # fragment-scoped: switches Panel 3 to progress view


_panel3()

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
        # Goal targets come from the baseline. In demo mode there is no real
        # baseline, so demo constants are the correct reference. In real mode a
        # missing baseline means every baseline replication failed — refuse to
        # score goals against fabricated demo targets, and say so loudly.
        if ss.baseline_agg is not None:
            _baseline: dict[str, float] | None = baseline_per_case(ss.baseline_agg)
        elif demo_mode:
            _baseline = baseline_per_case(demo.demo_baseline_agg())
        else:
            _baseline = None

        if _baseline is None:
            st.error(
                "Goal scoring is unavailable — all baseline replications failed, so "
                "there are no real targets to score against. Re-run to restore goal "
                "rankings. Scenario KPIs, main effects, and exports below remain valid.",
                icon="🚫",
            )
            goals: list[Goal] = []
        else:
            goals = [Goal.from_metric(_m, _baseline) for _m in _goal_specs]
        ranked = analysis.rank(agg, goals)
        show_factors = st.checkbox(
            "Show Taguchi factors", value=False, key="show_factors"
        )
        st.dataframe(
            prepare_ranked_display(ranked, _goal_specs, params, show_factors),
            use_container_width=True,
            hide_index=True,
        )
        st.markdown("###### Main effects")
        label_map = factor_label_map(params)
        _me_metrics = MetricRegistry.rankable()
        # rankable() guarantees per_case is set, so per_case_display_name is non-None.
        _me_labels: list[str] = []
        for _m in _me_metrics:
            assert _m.per_case_display_name is not None
            _me_labels.append(_m.per_case_display_name)
        _tabs = st.tabs(_me_labels)
        for _tab, _metric, _label in zip(_tabs, _me_metrics, _me_labels):
            with _tab:
                me = analysis.main_effects(ss.results, _metric)
                st.plotly_chart(
                    main_effects_chart(me, label_map, _label),
                    use_container_width=True,
                )

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
