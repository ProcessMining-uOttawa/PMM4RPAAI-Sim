"""Interactive discovery-config group (sidebar) — the Fast/Calibrated choice.

Part of ui/interactive/, so this module renders st.* widgets directly.
Discovery settings take effect at discovery time, not run time — which is why
this group is distinct from the Run config block, and why its caption tells
the user when the committed model was discovered with different settings than
the widgets now show ("Reset log" re-discovers with the current values). The
Fast/Calibrated radio is presentation only: it collapses to a single
`search_iterations: int | None` at the return (None = fast / one-shot —
Calibrated's identity IS its search budget, so an invalid mode/budget
combination is unrepresentable). No pure surface, so exercised manually like
app.py.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

_DEFAULT_ITERATIONS = 10
# Fidelity gain plateaus well before this cap, so it is an honest guard
# against an accidental multi-hour discovery, not a tuning ceiling.
_MAX_ITERATIONS = 30


def render_discovery_config(
    ss: Any, demo_mode: bool, discovery_running: bool
) -> int | None:
    """Render the discovery-mode widgets; return the collapsed search budget.

    None = fast (one-shot). Disabled in demo mode (no Simod) and while a
    discovery is in flight (the frozen widgets then show the values the run
    started with — starts only happen while no discovery is RUNNING for the
    upload in the uploader, i.e. while these widgets render enabled). Rendered
    disabled rather than hidden even in demo: RUNNING requires the frozen
    render anyway, so one mechanism serves both states, and app.py's
    "Discovery" header would otherwise need its own demo gate.
    """
    disabled = demo_mode or discovery_running
    mode = st.radio(
        "Discovery mode",
        ["Fast", "Calibrated"],
        horizontal=True,
        disabled=disabled,
        help="Fast: one discovery pass with defaults (~1–2 min). Calibrated: "
        "an optimization search that fits the model to the log (~4–8 min, "
        "scales with log size) — use it when the Model fidelity tab shows a "
        "poor fit.",
    )
    if mode == "Calibrated":
        search_iterations: int | None = int(
            st.number_input(
                "Search iterations",
                min_value=1,
                max_value=_MAX_ITERATIONS,
                value=_DEFAULT_ITERATIONS,
                disabled=disabled,
                help="Candidate models tried per discovery stage. Measured on "
                "test logs, fidelity plateaus by ~10 iterations — more mostly "
                "buys runtime.",
            )
        )
    else:
        search_iterations = None
    # Settings only apply at discovery time: when a discovered model exists and
    # was produced with different settings, say so rather than let the change
    # look ignored.
    if (
        not disabled
        and ss.activities
        and ss.discovery_search_iterations != search_iterations
    ):
        st.caption(
            "⚙ New settings apply on the next discovery — click **Reset log** "
            "to re-discover this log with them."
        )
    return search_iterations
