"""Interactive UI components.

Unlike the rest of ui/, modules in this subpackage may import streamlit and
render widgets directly. The boundary is structural: only modules under
ui/interactive/ call st.*; every other ui/ module stays Streamlit-free (and is
therefore unit-testable without an AppTest harness).
"""
