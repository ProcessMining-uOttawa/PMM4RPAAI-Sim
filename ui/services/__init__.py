"""Non-rendering UI services: Streamlit-free support the interactive components
consume — background-run lifecycles (run_manager, discovery_manager) and
environment detection (preflight).

The ui/ layering, by location: modules here are stateful or side-effectful but
never call st.* (unit-testable with plain objects); pure display-prep
primitives (table, plots, param_inputs) live at the ui/ top level; only
ui/interactive/ renders widgets. Dependencies flow
ui/interactive/ -> ui/services/ + ui/ top level -> core/.
"""
