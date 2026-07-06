"""Interactive manual-resource picker for Panel 1.

Part of ui/interactive/, so this module renders st.* widgets directly. A target
activity's resources are all human or all bot (never mixed); the user picks which
single resource's pool the num_manual_resources factor varies. Shared (multi-task)
resources are shown but frozen. Has no pure surface, so it is exercised manually
like app.py rather than unit-tested.
"""

from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from core.simulation.prosimos.query import ResourceSelectorConfig, resource_pool_size


@dataclass(frozen=True)
class ResourceSelection:
    """The pool choice resolved from the selector; None where not applicable."""

    selected_resource_id: str | None = None
    selected_pool_size: int | None = None
    frozen_pool_size: int | None = None


def _names(resources: list[dict]) -> list[str]:
    """Display names of a resource list ([{id, name}] dicts from core)."""
    return [resource["name"] for resource in resources]


def _halt_if_unresolved(pool_size: int | None) -> None:
    """Stop with a clear error when a task resource resolves to no profile.

    Should never happen with valid Simod output — Prosimos itself rejects such a
    model — so we surface it loudly rather than fabricating human-pool levels.
    """
    if pool_size is None:
        st.error(
            "A resource referenced by this task is not defined in any profile — "
            "the model JSON appears malformed."
        )
        st.stop()


def select_resource(
    config: ResourceSelectorConfig, prosimos_data: dict
) -> ResourceSelection:
    """Render the manual-resource picker and resolve the chosen pool size.

    Returns an empty selection (all None) when the task exposes no selectable or
    frozen resources — the no-info fallback that leaves the human pool unchanged.
    """
    if not (config.selectable or config.frozen):
        return ResourceSelection()

    if not config.selectable:
        # Every resource is shared across tasks — nothing is pickable.
        st.selectbox("Manual resource", _names(config.frozen), disabled=True)
        _halt_if_unresolved(config.fallback_pool_size)
        st.warning(
            "All resources are shared across tasks — "
            "Human pool size is frozen at its current value."
        )
        return ResourceSelection(frozen_pool_size=config.fallback_pool_size)

    if config.frozen:
        st.caption(f"Shared (frozen): {', '.join(_names(config.frozen))}")
    if len(config.selectable) == 1:
        selected_resource_id = config.selectable[0]["id"]
    else:
        selected_name = st.selectbox("Manual resource", _names(config.selectable))
        selected_resource_id = next(
            resource["id"]
            for resource in config.selectable
            if resource["name"] == selected_name
        )
    selected_pool_size = resource_pool_size(prosimos_data, selected_resource_id)
    _halt_if_unresolved(selected_pool_size)
    return ResourceSelection(
        selected_resource_id=selected_resource_id,
        selected_pool_size=selected_pool_size,
    )
