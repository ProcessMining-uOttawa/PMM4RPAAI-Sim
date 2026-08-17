"""Interactive factor-levels grid for Panel 2.

Part of ui/interactive/, so this module renders st.* widgets directly. It builds
the pattern's parameters (prepopulated from the Simod-discovered duration), renders
the Low/Mid/High number inputs per factor — or, when a factor's Pin checkbox is
on, a single input whose value fills all three levels (a design constant; see
core/taguchi.is_design_constant) — and returns the parameters with the user's
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

# Label column + three value cells + the Pin checkbox (label | low | mid | high | pin).
ROW_LAYOUT = [3, 1, 1, 1, 0.6]


def _level_input(
    column, parameter: Parameter, *, idx: int, suffix: str, disabled: bool = False
):
    """Render one factor-level number_input and return its value.

    The computed level is part of the widget key so the input re-defaults when its
    level changes (target → new t_manual, resource → new num_manual). A stable key
    would pin the widget to its first-render value and ignore the new `value=` (the
    "value is only the initial value" trap — see §6); factors with target-independent
    levels keep a constant key, so user edits survive a target switch.
    """
    return column.number_input(
        f"{parameter.id}_{suffix}",
        **number_input_kwargs(parameter.kind, parameter.levels[idx]),
        label_visibility="collapsed",
        key=f"{parameter.id}_{suffix}_{parameter.levels[idx]}",
        disabled=disabled,
    )


def configure_factor_levels(
    transformation: Transformation,
    prosimos_data: dict | None,
    task_id: str | None,
    selected_pool_size: int | None,
    frozen_pool_size: int | None,
) -> list[Parameter]:
    """Render the Low/Mid/High factor grid; return parameters with the user's edits.

    Prepopulates Non-Auto-Time from the Simod-discovered duration when available.
    A factor's Pin checkbox collapses its row to one editable input (seeded from
    Mid) filling all three levels — the editable twin of the frozen row.
    Unpinning restores default levels: the three inputs' state is garbage-
    collected while unmounted, and re-defaulting is accepted over a durable
    override store (the goals machinery) for an exploration control.
    The target activity itself is absent on purpose: factor declaration depends
    on the target only through the discovered context resolved by the caller
    (task_id -> duration, pool sizes), never on the activity's name.
    """
    current_duration_s = None
    if task_id is not None and prosimos_data is not None:
        current_duration_s = task_mean_duration_s(prosimos_data, task_id)
    parameters = transformation.parameters(
        current_duration_s=current_duration_s,
        selected_pool_size=selected_pool_size,
        frozen_pool_size=frozen_pool_size,
    )
    if current_duration_s is not None:
        st.caption(f"Non-Auto-Time pre-filled from Simod ({current_duration_s:.0f} s)")
    header = st.columns(ROW_LAYOUT)
    header[0].caption("Factor")
    for i, label in enumerate(("Low", "Mid", "High")):
        header[i + 1].caption(label)
    header[4].caption("Pin")
    for parameter in parameters:
        row = st.columns(ROW_LAYOUT)
        row[0].markdown(f"**{parameter.label}**")
        if parameter.frozen:
            _level_input(row[1], parameter, idx=0, suffix="frozen", disabled=True)
            row[2].caption("frozen")
        elif row[4].checkbox(
            f"Pin {parameter.label}",
            key=f"pin_{parameter.id}",
            label_visibility="collapsed",
            help="Pin this factor to one value: it leaves the design, so fewer "
            "scenarios run. Unpinning restores the default levels.",
        ):
            pinned_value = _level_input(row[1], parameter, idx=1, suffix="pinned")
            row[2].caption("pinned")
            parameter.levels = [pinned_value] * 3
        else:
            parameter.levels = [
                _level_input(row[i + 1], parameter, idx=i, suffix=str(i))
                for i in range(3)
            ]
    return parameters
