"""Streamlit dashboard — Mockup B layout."""

from __future__ import annotations
import json
import xml.etree.ElementTree as ET
import streamlit as st

from pathlib import Path
from core.transformations import REGISTRY
from core.experiment import build_scenarios
from core import analysis, demo, orchestrator, preflight
from core.simulation import runner, store
from core.constants import COL_CYCLE_H, COL_COST, COL_REWORK_RATE
from core.goals import Goal, baseline_per_case
from core.metrics import MetricRegistry
from ui.goals import GOAL_OPTIONS
from ui.plots import factor_label_map, main_effects_chart
from ui.widgets import level_input_kwargs
from core.bpmn.utils import (
    find_task_by_name,
    list_activities,
    task_mean_duration_s,
    resource_selector_config,
)

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
ss.setdefault("array_name", None)
ss.setdefault("scenarios", [])
ss.setdefault("baseline_agg", None)

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
            checks = preflight.run_checks()
            for c in checks:
                st.markdown(f"{'✅' if c.ok else '❌'} **{c.name}** — {c.detail}")
                if not c.ok and c.fix:
                    st.caption(c.fix)
            preflight_ok = preflight.all_ok(checks)
            detected = preflight.detect_corretto8() or ""
            java_home = (
                st.text_input(
                    "JAVA_HOME for Simod",
                    value=detected,
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
            ss.log_name = uploaded.name if uploaded else "sample log"
            ss.activities = demo.fake_discovery()
            ss.discovering = False
        else:
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
                    bpmn, params = runner.discover(
                        log_path,
                        run_dir,
                        java_home=java_home,
                        proc_log=store.discovery_log(run_dir),
                    )
                    ss.bpmn_path, ss.json_path = bpmn, params
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
            for k in (
                "log_name",
                "log_path",
                "activities",
                "bpmn_path",
                "json_path",
                "log_fingerprint",
                "results",
            ):
                ss[k] = None if k != "activities" else []
            ss.experiment_bpmn_path = None
            ss.scenario_json_paths = {}
            ss.baseline_agg = None
            st.rerun()

    st.divider()
    st.subheader("Goals")
    _goal_specs: list[tuple[str, float, float]] = []  # (col, pct, weight)
    _hdr = st.columns([3, 2, 1.5])
    _hdr[1].caption("Reduction (%)")
    _hdr[2].caption("Weight")
    for _m, _opt in GOAL_OPTIONS.items():
        _gcol = _m.per_case.mean.column
        _grow = st.columns([3, 2, 1.5])
        _grow[0].markdown(_m.per_case.mean.display_name)
        _pct = _grow[1].number_input(
            f"pct_{_gcol}",
            value=_opt.default_pct,
            min_value=0.0,
            max_value=99.0,
            step=_opt.step,
            key=f"goal_pct_{_gcol}",
            label_visibility="collapsed",
        )
        _wt = _grow[2].number_input(
            f"wt_{_gcol}",
            value=_opt.default_weight,
            min_value=0.0,
            max_value=1.0,
            step=0.05,
            key=f"goal_weight_{_gcol}",
            label_visibility="collapsed",
        )
        _goal_specs.append((_gcol, _pct, _wt))

    _weight_sum = sum(wt for _, _, wt in _goal_specs)
    if abs(_weight_sum - 1.0) > 0.01:
        st.warning(f"Weights sum to {_weight_sum:.2f} — scores will be skewed unless they sum to 1.")

    st.divider()
    st.subheader("Run config")
    n_reps = st.number_input("Replications (N)", 1, 100, 5)
    bot_cost_per_hour = st.number_input("Bot cost ($/hr)", min_value=0.0, value=0.0, step=1.0)

# --- gate: need a log first --------------------------------------------------
if not ss.activities:
    st.info("Upload a log or click **Use sample log** in the sidebar to begin.")
    st.stop()

# --- main: 2x2 dashboard -----------------------------------------------------
col1, col2 = st.columns(2)

with col1:
    with st.container(border=True):
        st.markdown("##### 1 · Activity & pattern")
        target = st.selectbox("Target activity", ss.activities, index=1)

        # Load model info — results shared with col2 (duration prepopulation).
        _task_id: str | None = None
        prosimos_data: dict | None = None
        _resource_cfg = None
        if ss.bpmn_path and ss.json_path and not demo_mode:
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

        # Resource selector — only shown in non-demo mode when task has multiple resources.
        selected_resource_id: str | None = None
        frozen_pool_size: int | None = None

        if _resource_cfg is not None:
            cfg = _resource_cfg
            if cfg.selectable or cfg.frozen:
                if not cfg.selectable:
                    st.selectbox(
                        "Manual resource",
                        [r["name"] for r in cfg.frozen],
                        disabled=True,
                    )
                    if cfg.frozen_pool_size is None:
                        st.warning(
                            "All resources are shared across tasks — "
                            "resource not found in profiles; pool size unknown."
                        )
                    else:
                        st.warning(
                            "All resources are shared across tasks — "
                            "Human pool size is frozen at its current value."
                        )
                        frozen_pool_size = cfg.frozen_pool_size
                else:
                    if cfg.frozen:
                        st.caption(
                            f"Shared (frozen): {', '.join(r['name'] for r in cfg.frozen)}"
                        )
                    if len(cfg.selectable) == 1:
                        selected_resource_id = cfg.selectable[0]["id"]
                    else:
                        _sel_name = st.selectbox(
                            "Manual resource", [r["name"] for r in cfg.selectable]
                        )
                        selected_resource_id = next(
                            r["id"] for r in cfg.selectable if r["name"] == _sel_name
                        )

        pattern_id = st.selectbox(
            "Substitution pattern",
            list(REGISTRY.keys()),
            format_func=lambda k: REGISTRY[k].label,
        )

with col2:
    with st.container(border=True):
        st.markdown("##### 2 · Factor levels")
        transformation = REGISTRY[pattern_id]
        # Prepopulate Non-Auto-Time from Simod's discovered duration when available.
        current_dur = None
        if _task_id is not None and prosimos_data is not None:
            current_dur = task_mean_duration_s(prosimos_data, _task_id)
        params = transformation.parameters(
            target,
            current_duration_s=current_dur,
            selected_resource_id=selected_resource_id,
            frozen_pool_size=frozen_pool_size,
        )
        if current_dur is not None:
            st.caption(f"Non-Auto-Time pre-filled from Simod ({current_dur:.0f} s)")
        hdr = st.columns([3, 1, 1, 1])
        hdr[0].caption("Factor")
        for i, lbl in enumerate(("Low", "Mid", "High")):
            hdr[i + 1].caption(lbl)
        for p in params:
            row = st.columns([3, 1, 1, 1])
            row[0].markdown(f"**{p.label}**")
            if p.frozen:
                row[1].number_input(
                    f"{p.id}_frozen",
                    **level_input_kwargs(p.kind, p.levels[0]),
                    label_visibility="collapsed",
                    key=f"{p.id}_frozen",
                    disabled=True,
                )
                row[2].caption("frozen")
            else:
                new = []
                for i in range(3):
                    new.append(
                        row[i + 1].number_input(
                            f"{p.id}_{i}",
                            **level_input_kwargs(p.kind, p.levels[i]),
                            label_visibility="collapsed",
                            key=f"{p.id}_{i}",
                        )
                    )
                p.levels = new

# --- Design + execution panel ------------------------------------------------
array_name, scenarios = build_scenarios(params, transformation.id, target)
ss.array_name, ss.scenarios = array_name, scenarios
total_runs = len(scenarios) * n_reps

with st.container(border=True):
    left, right = st.columns([3, 1])
    left.markdown(
        f"##### 3 · Execution  "
        f"<span style='background:#eef2ff;color:#3b6cf2;font-size:11px;"
        f"padding:2px 8px;border-radius:10px'>{array_name} · "
        f"{len(scenarios)} scenarios × {n_reps} reps = {total_runs} runs</span>",
        unsafe_allow_html=True,
    )
    run_clicked = right.button(
        "▶ Run all scenarios", type="primary", use_container_width=True
    )

    if run_clicked:
        if not demo_mode and (not ss.bpmn_path or not ss.json_path):
            st.error("No discovered model — upload a log first.")
            st.stop()
        progress = st.progress(0.0, text="Starting…")

        def _on_progress(done: int, total: int, sid: str, rep: int) -> None:
            progress.progress(
                done / total, text=f"Scenario {sid} · rep {rep + 1}/{n_reps}"
            )

        if demo_mode:
            result = demo.run_experiment(scenarios, n_reps, _on_progress,
                                         bot_cost_per_hour=bot_cost_per_hour)
        else:
            exp_dir = store.new_experiment(ss.log_name or "run")
            result = orchestrator.run_experiment(
                transformation=transformation,
                bpmn_path=ss.bpmn_path,
                json_path=ss.json_path,
                target=target,
                scenarios=scenarios,
                n_reps=n_reps,
                exp_dir=exp_dir,
                on_progress=_on_progress,
                selected_resource_id=selected_resource_id,
                bot_cost_per_hour=bot_cost_per_hour,
            )
        ss.results = result.results
        ss.experiment_bpmn_path = result.experiment_bpmn_path
        ss.scenario_json_paths = result.scenario_json_paths
        ss.baseline_agg = result.baseline_agg
        progress.empty()
        st.success(f"Completed {total_runs} simulations.")

# --- Results panel -----------------------------------------------------------
if ss.results is not None:
    agg = analysis.aggregate(ss.results)

    with st.container(border=True):
        st.markdown("##### 4 · Ranked scenarios")
        if ss.results[COL_COST].isna().any():
            st.warning(
                "Cost data is unavailable for one or more runs — Prosimos did not "
                "produce a stats CSV with a parseable 'Individual Task Statistics' section. "
                "Cost goals are marked unmet.",
                icon="⚠️",
            )
        _baseline = baseline_per_case(ss.baseline_agg or demo.demo_baseline_agg())
        goals = [
            Goal.from_pct_reduction(col, wt, pct, _baseline[col])
            for col, pct, wt in _goal_specs
        ]
        ranked = analysis.rank(agg, goals)
        ranked.insert(0, "rank", range(1, len(ranked) + 1))
        _kpi_rename = {"scenario_id": "Scenario"}
        _std_cols = []
        _agg_transforms: dict[str, object] = {}
        for _m in MetricRegistry.all():
            if _m.per_case:
                _kpi_rename[_m.per_case.mean.column] = _m.per_case.mean.display_name
                if _m.per_case.std:
                    _std_cols.append(_m.per_case.std.column)
            if _m.aggregate:
                _kpi_rename[_m.aggregate.column] = _m.aggregate.display_name
                _agg_transforms[_m.aggregate.column] = _m.aggregate.display_fn
        _per_goal_rename = {
            f"{g.metric}_met": MetricRegistry.by_column(g.metric).display_name + " ✓"
            for g in goals if g.weight != 0
        }
        st.dataframe(
            ranked.assign(
                **{col: ranked[col].map({True: "✓", False: "✗"})
                   for col in _per_goal_rename if col in ranked.columns},
                **{col: ranked[col].map(fn)  # type: ignore[arg-type]
                   for col, fn in _agg_transforms.items() if col in ranked.columns},
            ).drop(columns=["goal_met", "score"] + _std_cols, errors="ignore")
             .rename(columns={**_kpi_rename, **_per_goal_rename, **{p.id: p.label for p in params}}),
            use_container_width=True,
            hide_index=True,
        )
        st.markdown("###### Main effects (smaller is better)")
        label_map = factor_label_map(params)
        _me_metrics = [
            (MetricRegistry.CYCLE_TIME, COL_CYCLE_H),
            (MetricRegistry.COST,       COL_COST),
            (MetricRegistry.REWORK_RATE, COL_REWORK_RATE),
        ]
        tab_cycle, tab_cost, tab_rework = st.tabs(
            [m.per_case.mean.display_name for m, _ in _me_metrics]
        )
        for _tab, (_metric, _col) in zip(
            [tab_cycle, tab_cost, tab_rework], _me_metrics
        ):
            with _tab:
                me = analysis.main_effects(ss.results, _col, direction=_metric.per_case.mean.direction, floor=_metric.sn_floor)
                st.plotly_chart(
                    main_effects_chart(me, label_map, _metric.per_case.mean.display_name),
                    use_container_width=True,
                )

        bpmn_path = ss.get("experiment_bpmn_path")
        bpmn_exists = bpmn_path and Path(bpmn_path).exists()
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
        col_bpmn, col_json, col_stats, col_all = st.columns(4)
        col_json.download_button(
            "⬇ Scenarios (JSON zip)",
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
            data=Path(bpmn_path).read_bytes() if bpmn_exists else b"",
            file_name="model.bpmn",
            mime="application/xml",
            use_container_width=True,
            disabled=not bpmn_exists,
        )
        col_all.download_button(
            "⬇ All (ZIP)",
            data=store.group_zip(Path(bpmn_path), json_paths, stats_csv) if (bpmn_exists and json_paths) else b"",
            file_name="export.zip",
            mime="application/zip",
            use_container_width=True,
            disabled=not (bpmn_exists and json_paths),
        )

    baseline_agg = ss.get("baseline_agg")
    if baseline_agg:
        with st.container(border=True):
            st.markdown("##### 5 · Baseline comparison")
            st.caption(
                "Total metrics averaged across replications. "
                "Δ values are relative to the original process (no automation)."
            )
            st.dataframe(
                analysis.compare_to_baseline(agg, baseline_agg),
                use_container_width=True,
                hide_index=True,
            )
