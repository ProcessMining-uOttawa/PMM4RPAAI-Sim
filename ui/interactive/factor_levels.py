"""Interactive factor-levels grid for Panel 2.

Part of ui/interactive/, so this module renders st.* widgets directly. It builds
the pattern's parameters (prepopulated from the Simod-discovered duration), renders
the Low/Mid/High number inputs per factor, and returns the params with the user's
edited levels. Consumes the pure ui/param_inputs helper — the first instance of the
ui/interactive -> ui/ (presentation primitives) dependency. Has no pure surface, so
it is exercised manually like app.py rather than unit-tested.
"""

from __future__ import annotations

import streamlit as st

from core.parameters import Parameter
from core.simulation.prosimos.query import task_mean_duration_s
from core.transformations import Transformation
from ui.param_inputs import number_input_kwargs


def render_factor_levels(
    transformation: Transformation,
    target: str,
    prosimos_data: dict | None,
    task_id: str | None,
    selected_pool_size: int | None,
    frozen_pool_size: int | None,
) -> list[Parameter]:
    """Render the Low/Mid/High factor grid and return params with edited levels.

    Prepopulates Non-Auto-Time from the Simod-discovered duration when available.
    """
    current_dur = None
    if task_id is not None and prosimos_data is not None:
        current_dur = task_mean_duration_s(prosimos_data, task_id)
    params = transformation.parameters(
        target,
        current_duration_s=current_dur,
        selected_pool_size=selected_pool_size,
        frozen_pool_size=frozen_pool_size,
    )
    if current_dur is not None:
        st.caption(f"Non-Auto-Time pre-filled from Simod ({current_dur:.0f} s)")
    hdr = st.columns([3, 1, 1, 1])
    hdr[0].caption("Factor")
    for i, lbl in enumerate(("Low", "Mid", "High")):
        hdr[i + 1].caption(lbl)
    # The computed level value is part of each widget key so the input
    # re-defaults when its level changes — e.g. switching target gives a new
    # t_manual mean, switching resource a new num_manual pool. A stable key
    # would pin the widget to its first-render value and ignore the new
    # `value=` (the "value is only the initial value" trap — see §6); fixed
    # factors keep a constant key, so user edits to them survive a target switch.
    for p in params:
        row = st.columns([3, 1, 1, 1])
        row[0].markdown(f"**{p.label}**")
        if p.frozen:
            row[1].number_input(
                f"{p.id}_frozen",
                **number_input_kwargs(p.kind, p.levels[0]),
                label_visibility="collapsed",
                key=f"{p.id}_frozen_{p.levels[0]}",
                disabled=True,
            )
            row[2].caption("frozen")
        else:
            new = []
            for i in range(3):
                new.append(
                    row[i + 1].number_input(
                        f"{p.id}_{i}",
                        **number_input_kwargs(p.kind, p.levels[i]),
                        label_visibility="collapsed",
                        key=f"{p.id}_{i}_{p.levels[i]}",
                    )
                )
            p.levels = new
    return params
