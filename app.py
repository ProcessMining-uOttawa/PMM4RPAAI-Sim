"""Streamlit dashboard — Mockup B layout."""

from __future__ import annotations
import io
import json
import xml.etree.ElementTree as ET
import zipfile
import streamlit as st

from pathlib import Path
from core.transformations import REGISTRY
from core.experiment import build_scenarios
from core import analysis, demo, orchestrator, preflight
from core.simulation import runner, store
from core.constants import COL_CYCLE_H, COL_COST, COL_REWORK_RATE
from ui.goals import GOAL_OPTIONS
from ui.widgets import level_input_kwargs
from core.bpmn.utils import (
    find_task_by_name,
    list_activities,
    task_mean_duration_s,
    task_resources,
    shared_resource_ids,
    resource_pool_size,
)

st.set_page_config(
    page_title="Automation What-If Simulator", page_icon="⚙", layout="wide"
)


def _json_zip(json_paths: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for sid, p in sorted(json_paths.items()):
            z.writestr(f"scenarios/{sid}_params.json", p.read_text())
    return buf.getvalue()


def _group_zip(bpmn_path: Path, json_paths: dict, stats_csv: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(str(bpmn_path), arcname="model.bpmn")
        z.writestr("statistics.csv", stats_csv)
        for sid, p in sorted(json_paths.items()):
            z.writestr(f"scenarios/{sid}_params.json", p.read_text())
    return buf.getvalue()


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
    goal_label = st.selectbox("Optimise for", GOAL_OPTIONS)
    opt = GOAL_OPTIONS[goal_label]
    goal_max = st.number_input(
        "Target ≤", value=opt.default, step=opt.step, key=f"goal_max_{opt.col}"
    )

    st.divider()
    st.subheader("Run config")
    n_reps = st.number_input("Replications (N)", 1, 100, 5)

# --- gate: need a log first --------------------------------------------------
if not ss.activities:
    st.info("Upload a log or click **Use sample log** in the sidebar to begin.")
    st.stop()

# --- main: 2x2 dashboard -----------------------------------------------------
col1, col2 = st.columns(2)

# Load Prosimos JSON once; shared between col1 (resource detection) and col2 (duration prepopulation).
prosimos_data: dict | None = None
target_el: ET.Element | None = None

with col1:
    with st.container(border=True):
        st.markdown("##### 1 · Activity & pattern")
        target = st.selectbox("Target activity", ss.activities, index=1)

        # Resource selector — only shown in non-demo mode when task has multiple resources.
        selected_resource_id: str | None = None
        frozen_pool_size: int | None = None

        if ss.bpmn_path and ss.json_path and not demo_mode:
            try:
                _tree = ET.parse(str(ss.bpmn_path))
                target_el = find_task_by_name(_tree, target)
                if target_el is not None:
                    prosimos_data = json.loads(Path(ss.json_path).read_text())
                    _task_id = target_el.get("id")
                    _resources = task_resources(prosimos_data, _task_id)
                    if len(_resources) == 1:
                        selected_resource_id = _resources[0]["id"]
                    elif len(_resources) > 1:
                        _shared = shared_resource_ids(prosimos_data)
                        _selectable = [r for r in _resources if r["id"] not in _shared]
                        _frozen = [r for r in _resources if r["id"] in _shared]
                        if _selectable:
                            if _frozen:
                                st.caption(
                                    f"Shared (frozen): {', '.join(r['name'] for r in _frozen)}"
                                )
                            _sel_name = st.selectbox(
                                "Manual resource", [r["name"] for r in _selectable]
                            )
                            selected_resource_id = next(
                                r["id"] for r in _selectable if r["name"] == _sel_name
                            )
                        else:
                            # All resources are shared — freeze the pool factor.
                            st.selectbox(
                                "Manual resource",
                                [r["name"] for r in _resources],
                                disabled=True,
                            )
                            _pool = resource_pool_size(
                                prosimos_data, _resources[0]["id"]
                            )
                            if _pool is None:
                                st.warning(
                                    "All resources are shared across tasks — "
                                    "resource not found in profiles; pool size unknown."
                                )
                            else:
                                st.warning(
                                    "All resources are shared across tasks — "
                                    "Human pool size is frozen at its current value."
                                )
                                frozen_pool_size = _pool
            except Exception:
                pass

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
        if target_el is not None and prosimos_data is not None:
            try:
                current_dur = task_mean_duration_s(prosimos_data, target_el.get("id"))
            except Exception:
                pass
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
            result = demo.run_experiment(scenarios, n_reps, _on_progress)
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
        if goal_max < 0 or (not opt.allow_zero and goal_max == 0):
            st.error("Target must be a positive number.")
            st.stop()
        ranked = analysis.rank(agg, opt.col, goal_max * opt.scale)
        ranked.insert(0, "rank", range(1, len(ranked) + 1))
        st.dataframe(
            ranked.assign(
                goals=ranked["goal_met"].map({True: "✓ met", False: "✗"})
            ).drop(columns=["goal_met", "score"]),
            use_container_width=True,
            hide_index=True,
        )
        if opt.allow_zero and goal_max == 0:
            st.caption(
                "Score shows raw rework rate (lower is better). "
                "Ratio-to-target is undefined when the target is zero."
            )

        st.markdown("###### Main effects (smaller is better)")
        tab_cycle, tab_cost, tab_rework = st.tabs(["Cycle time", "Cost", "Rework rate"])
        with tab_cycle:
            me = analysis.main_effects(ss.results, COL_CYCLE_H)
            st.dataframe(me, use_container_width=True, hide_index=True)
        with tab_cost:
            me = analysis.main_effects(ss.results, COL_COST)
            st.dataframe(me, use_container_width=True, hide_index=True)
        with tab_rework:
            me = analysis.main_effects(ss.results, COL_REWORK_RATE)
            st.dataframe(me, use_container_width=True, hide_index=True)
            if me["sn"].isna().any():
                st.caption(
                    "S/N is NaN for factor levels where all replications have zero "
                    "rework rate — the log formula requires positive values."
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
        if json_paths:
            col_json.download_button(
                "⬇ Scenarios (JSON zip)",
                _json_zip(json_paths),
                file_name="scenarios.zip",
                mime="application/zip",
                use_container_width=True,
            )
        col_stats.download_button(
            "⬇ Statistics (CSV)",
            stats_csv,
            file_name="statistics.csv",
            mime="text/csv",
            use_container_width=True,
        )
        if bpmn_exists:
            col_bpmn.download_button(
                "⬇ BPMN",
                Path(bpmn_path).read_bytes(),
                file_name="model.bpmn",
                mime="application/xml",
                use_container_width=True,
            )
        if bpmn_exists and json_paths:
            col_all.download_button(
                "⬇ All (ZIP)",
                _group_zip(Path(bpmn_path), json_paths, stats_csv),
                file_name="export.zip",
                mime="application/zip",
                use_container_width=True,
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
