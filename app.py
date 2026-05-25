"""Streamlit dashboard — Mockup B layout."""
from __future__ import annotations
import io, time, zipfile
import pandas as pd
import streamlit as st

from pathlib import Path
from core.transformations import REGISTRY
from core.experiment import build_scenarios
from core import analysis, demo, preflight, runner, store

st.set_page_config(page_title="Automation What-If Simulator",
                   page_icon="⚙", layout="wide")

# --- session state defaults --------------------------------------------------
ss = st.session_state
ss.setdefault("log_name", None)
ss.setdefault("log_path", None)       # Path to uploaded log
ss.setdefault("activities", [])
ss.setdefault("bpmn_path", None)
ss.setdefault("json_path", None)
ss.setdefault("results", None)        # tidy per-replication DataFrame
ss.setdefault("scenario_bpmn_paths", {})  # sid -> Path, populated after each run
ss.setdefault("array_name", None)
ss.setdefault("scenarios", [])

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
    demo_mode = st.toggle("Demo mode (no Simod/Prosimos)", value=True,
                          help="Uses synthetic discovery + simulation so you can "
                               "click through the UI without external tools.")

    if not demo_mode:
        with st.expander("Simod preflight", expanded=True):
            checks = preflight.run_checks()
            for c in checks:
                st.markdown(f"{'✅' if c.ok else '❌'} **{c.name}** — {c.detail}")
                if not c.ok and c.fix:
                    st.caption(c.fix)
            preflight_ok = preflight.all_ok(checks)
            detected = preflight.detect_corretto8() or ""
            java_home = st.text_input(
                "JAVA_HOME for Simod", value=detected,
                help="Used only for Simod's subprocess; leaves your system Java alone.",
            ) or None
    else:
        preflight_ok, java_home = True, None

    uploaded = st.file_uploader("Event log (XES or CSV)", type=["xes", "csv"])
    use_sample = st.button("Use sample log", use_container_width=True)

    # Fingerprint the upload so we only discover ONCE per unique file.
    # CRITICAL: Streamlit reruns the script top-to-bottom on every interaction,
    # even while a slow synchronous subprocess is mid-flight. To prevent
    # launching concurrent Simod processes we set the fingerprint BEFORE the
    # subprocess call (so concurrent reruns short-circuit immediately) and
    # also hold a per-session "discovering" lock.
    upload_fp = (uploaded.name, uploaded.size) if uploaded else None
    already_discovered = ss.get("log_fingerprint") == upload_fp and ss.activities
    discovering        = ss.get("discovering", False)

    needs_discovery = (
        (uploaded and not already_discovered and not discovering)
        or (use_sample and demo_mode and not ss.activities)
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
            with st.status("Running Simod discovery (~2 min for 100k events)…",
                           expanded=True) as s:
                try:
                    bpmn, params = runner.discover(log_path, run_dir, java_home=java_home)
                    ss.bpmn_path, ss.json_path = bpmn, params
                    ss.activities = runner.list_activities(bpmn)
                    ss.log_name, ss.log_path = uploaded.name, log_path
                    s.update(label=f"Discovered {len(ss.activities)} activities", state="complete")
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
            for k in ("log_name", "log_path", "activities", "bpmn_path",
                      "json_path", "log_fingerprint", "results"):
                ss[k] = None if k != "activities" else []
            ss.scenario_bpmn_paths = {}
            st.rerun()

    st.divider()
    st.subheader("Goals")
    goal_cycle = st.number_input("Cycle time ≤ (hours)", value=24.0, step=1.0)
    goal_cost  = st.number_input("Cost ≤ ($/case)",      value=40.0, step=1.0)

    st.divider()
    st.subheader("Run config")
    n_reps   = st.number_input("Replications (N)", 1, 100, 5)
    n_cases  = st.number_input("Cases per rep (C)", 10, 100_000, 500, step=100)

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
        if ss.bpmn_path and ss.json_path and not demo_mode:
            try:
                from lxml import etree
                from core.bpmn_utils import find_task_by_name, task_mean_duration_s
                _tree = etree.parse(str(ss.bpmn_path))
                _t = find_task_by_name(_tree, target)
                if _t is not None:
                    import json as _json
                    _data = _json.loads(Path(ss.json_path).read_text())
                    current_dur = task_mean_duration_s(_data, _t.get("id"))
            except Exception:
                pass
        params = transformation.parameters(target, current_duration_s=current_dur)
        edited_levels: dict[str, list] = {}
        hdr = st.columns([3, 1, 1, 1])
        hdr[0].caption("Factor")
        for i, lbl in enumerate(("Low", "Mid", "High")):
            hdr[i+1].caption(lbl)
        for p in params:
            row = st.columns([3, 1, 1, 1])
            row[0].markdown(f"**{p.label}**")
            new = []
            for i in range(3):
                new.append(row[i+1].number_input(
                    f"{p.id}_{i}", value=float(p.levels[i]),
                    label_visibility="collapsed", key=f"{p.id}_{i}",
                ))
            edited_levels[p.id] = new
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
    run_clicked = right.button("▶ Run all scenarios", type="primary",
                               use_container_width=True)

    if run_clicked:
        ss.scenario_bpmn_paths = {}
        progress = st.progress(0.0, text="Starting…")
        rows = []
        done = 0
        for s in scenarios:
            for rep in range(n_reps):
                if demo_mode:
                    r = demo.fake_simulate(s, rep, n_cases)
                    cycle_h, cost = r.cycle_h, r.cost
                else:
                    if not ss.bpmn_path or not ss.json_path:
                        st.error("No discovered model — upload a log first.")
                        st.stop()
                    rep_dir = Path(f"runs/_active/{s.id}")
                    # Apply the substitution transformation per scenario (once
                    # per scenario; reused across replications).
                    if rep == 0:
                        tr = transformation.apply(
                            ss.bpmn_path, ss.json_path, target,
                            s.values, rep_dir)
                        s_bpmn, s_json = tr.bpmn_path, tr.json_path
                        ss.scenario_bpmn_paths[s.id] = tr.bpmn_path
                    out_log  = rep_dir / f"rep_{rep:03d}_log.csv"
                    out_stat = rep_dir / f"rep_{rep:03d}_stats.csv"
                    runner.simulate(s_bpmn, s_json,
                                    int(n_cases), out_log, stat_out=out_stat)
                    m = analysis.per_log_metrics(out_log, out_stat)
                    cycle_h, cost = m["cycle_h"], m["cost"]
                rows.append({"scenario_id": s.id, "replication": rep,
                             "cycle_h": cycle_h, "cost": cost,
                             **{k: v for k, v in s.values.items()}})
                done += 1
                progress.progress(done/total_runs,
                                  text=f"Scenario {s.id} · rep {rep+1}/{n_reps}")
        ss.results = pd.DataFrame(rows)
        progress.empty()
        st.success(f"Completed {total_runs} simulations.")

# --- Results panel -----------------------------------------------------------
if ss.results is not None:
    with st.container(border=True):
        st.markdown("##### 4 · Ranked scenarios")
        agg = analysis.aggregate(ss.results)
        ranked = analysis.rank(agg, goals={
            "cycle_h_mean": {"max": goal_cycle},
            "cost_mean":    {"max": goal_cost},
        })
        show = ranked.copy()
        show.insert(0, "rank", range(1, len(show)+1))
        show["goals"] = show["goals_met"].map({True: "✓ both", False: "✗"})
        st.dataframe(
            show.drop(columns=["goals_met"]),
            use_container_width=True, hide_index=True,
        )

        st.markdown("###### Main effects (smaller is better)")
        tab_cycle, tab_cost = st.tabs(["Cycle time", "Cost"])
        with tab_cycle:
            me = analysis.main_effects(ss.results, "cycle_h")
            st.dataframe(me, use_container_width=True, hide_index=True)
        with tab_cost:
            me = analysis.main_effects(ss.results, "cost")
            st.dataframe(me, use_container_width=True, hide_index=True)

        bpmn_paths = {sid: Path(p) for sid, p in ss.scenario_bpmn_paths.items()
                      if Path(p).exists()}
        if bpmn_paths:
            st.markdown("###### Download transformed BPMNs")
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for sid, bpath in bpmn_paths.items():
                    zf.write(bpath, arcname=f"scenario_{sid}.bpmn")
            buf.seek(0)
            st.download_button(
                "⬇ Download all scenario BPMNs (.zip)",
                buf.getvalue(),
                file_name="scenario_bpmns.zip",
                mime="application/zip",
            )
