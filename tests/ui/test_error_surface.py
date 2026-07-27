"""Tests for error_log_tail — the pure half of the shared failure surface.

The rendering half (render_failure) is an st-calling component exercised
manually like its ui/interactive siblings; the tail accessor is the part with
a contract worth pinning (two producer conventions feeding one expander).
"""

from __future__ import annotations

from subprocess import CalledProcessError

from core.orchestrator import SimulationError
from core.transformations import TransformValidationError
from ui.interactive.error_surface import error_log_tail


class TestErrorLogTail:
    def test_simulation_error_log_tail(self):
        assert error_log_tail(SimulationError("boom", log_tail="the tail")) == (
            "the tail"
        )

    def test_log_tail_attribute_wins_over_output(self):
        # A contested read: both conventions present on one error — the
        # log_tail attribute must take precedence over CalledProcessError.output.
        err = CalledProcessError(1, ["prosimos"], output="the output")
        err.log_tail = "the tail"
        assert error_log_tail(err) == "the tail"

    def test_transform_validation_error_tail(self, tmp_path):
        err = TransformValidationError(
            "bad model", tmp_path / "validation.log", log_tail="ERROR X: y"
        )
        assert error_log_tail(err) == "ERROR X: y"

    def test_called_process_error_output_fallback(self):
        err = CalledProcessError(1, ["prosimos"], output="last 20 lines")
        assert error_log_tail(err) == "last 20 lines"

    def test_no_tail_returns_none(self):
        assert error_log_tail(ValueError("plain message")) is None

    def test_empty_output_returns_none(self):
        # A subprocess failure with nothing captured must not render an
        # empty expander.
        assert error_log_tail(CalledProcessError(1, ["prosimos"], output="")) is None
