"""Interactive Simod preflight panel for the sidebar.

Part of ui/interactive/, so this module renders st.* widgets directly. Renders the
Simod preflight expander (Python/Java/venv checks + JAVA_HOME override) in
non-demo mode; demo mode never invokes Simod or Prosimos subprocesses, so there is
nothing to check. Consumes the pure ui/preflight helpers (run_checks, all_ok) — a
ui/interactive -> ui/ (presentation primitives) dependency. Has no pure surface, so
it is exercised manually like app.py rather than unit-tested.
"""

from __future__ import annotations

import streamlit as st

from ui import preflight


def render_simod_preflight(demo_mode: bool) -> tuple[bool, str | None]:
    """Render the Simod preflight expander; return (all_checks_ok, java_home).

    Skipped entirely in demo mode — nothing to check — returning (True, None).
    """
    if demo_mode:
        return True, None
    with st.expander("Simod preflight", expanded=True):
        checks, detected_java = preflight.run_checks()
        for check in checks:
            st.markdown(
                f"{'✅' if check.ok else '❌'} **{check.name}** — {check.detail}"
            )
            if not check.ok and check.fix:
                st.caption(check.fix)
        java_home = (
            st.text_input(
                "JAVA_HOME for Simod",
                value=detected_java or "",
                help="Used only for Simod's subprocess; leaves your system Java alone.",
            )
            or None
        )
        return preflight.all_ok(checks), java_home
