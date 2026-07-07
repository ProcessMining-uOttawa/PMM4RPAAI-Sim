"""Interactive discovery-progress panel (sidebar).

Part of ui/interactive/, so it renders st.* and owns a @st.fragment — the
discovery counterpart to execution_panel. While a discovery is RUNNING this
fragment polls the DiscoverySession on a `run_every` timer: those auto-reruns are
fragment-scoped (only this panel re-renders — no full-page flicker, and no
app-scoped st.rerun() storm to swallow the Cancel click). On success it commits
the result and does one `st.rerun(scope="app")`; on Cancel it marks the session
and reruns; a FAILED session is detected here too and handed to app.py's settled
banner via one app rerun. Consumes ui/discovery_manager (a ui/interactive -> ui/
dependency). No pure surface, so it is exercised manually like app.py.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from ui.discovery_manager import (
    cancel_discovery,
    clear_discovery,
    commit_discovery,
    current_discovery,
)

# Poll cadence for the background discovery. Discovery takes ~2 min, so a
# 1 s timer detects completion promptly while keeping auto-reruns sparse.
_POLL_SECONDS = 1.0


@st.fragment(run_every=_POLL_SECONDS)
def render_discovery_progress(ss: Any) -> None:
    """Poll the RUNNING discovery; commit on success, hand off on cancel/failure.

    The `run_every` timer re-runs only this fragment (no page flicker). Every
    exit path does one `st.rerun(scope="app")`, which also stops the timer (the
    next full run no longer renders this fragment). app.py gates the call on
    discovery_phase() == RUNNING, so a session exists and is not yet terminal.
    """
    session = current_discovery(ss)
    if session is None:  # defensive — app.py only calls this while RUNNING
        return
    outcome = session.outcome

    if outcome is None:
        st.info("⏳ Running Simod discovery (~2 min for 100k events)…")
        if st.button("Cancel discovery"):
            # The Simod subprocess keeps running (same limitation as a
            # simulation cancel), but we stop waiting; app.py shows the
            # cancelled banner and won't auto-re-discover this upload.
            cancel_discovery(ss)
            st.rerun(scope="app")
        return

    if outcome.error is not None:
        # Let app.py render the FAILED banner (discovery_phase → FAILED).
        st.rerun(scope="app")
        return

    # No error → result is set (DiscoveryOutcome invariant).
    assert outcome.result is not None
    commit_discovery(ss, outcome.result, session.fingerprint)
    clear_discovery(ss)
    st.rerun(scope="app")
