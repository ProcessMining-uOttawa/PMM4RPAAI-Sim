"""Shared failure surface: an error banner with an optional captured-log expander.

One render shape, multiple producers — a Simod discovery failure
(``CalledProcessError.output``), a hard run failure (``SimulationError.log_tail``),
and a transform-validation failure (``TransformValidationError.log_tail``). The
caller owns the message policy (what to say, which errors deserve a traceback);
this component owns the rendering.
"""

from __future__ import annotations

from subprocess import CalledProcessError

import streamlit as st


def error_log_tail(error: Exception) -> str | None:
    """The captured log tail an error carries, if any.

    Two conventions feed the same expander: our exceptions attach ``log_tail``
    (SimulationError, TransformValidationError), while a subprocess failure
    carries the runner-captured tail as ``CalledProcessError.output`` — which
    ``str(error)`` omits, so it must be read explicitly or the real error never
    reaches the user.
    """
    tail = getattr(error, "log_tail", None)
    if tail:
        return str(tail)
    if isinstance(error, CalledProcessError) and error.output:
        return str(error.output)
    return None


def render_failure(
    message: str,
    error: Exception | None = None,
    *,
    expander_label: str = "Output (log tail)",
    icon: str | None = None,
    show_traceback: bool = False,
) -> None:
    """Render ``st.error`` + optional traceback + optional captured-log expander."""
    st.error(message, icon=icon)
    if error is None:
        return
    if show_traceback:
        st.exception(error)
    tail = error_log_tail(error)
    if tail:
        with st.expander(expander_label):
            st.code(tail)
