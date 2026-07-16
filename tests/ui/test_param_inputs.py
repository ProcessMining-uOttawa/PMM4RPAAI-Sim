"""Tests for ui/param_inputs.py — st.number_input kwargs per Parameter.kind."""

from __future__ import annotations

from ui.param_inputs import number_input_kwargs


class TestNumberInputKwargs:
    def test_percentage(self):
        assert number_input_kwargs("percentage", 50) == {
            "value": 50.0,
            "min_value": 0.0,
            "max_value": 100.0,
            "step": 1.0,
            "format": "%.0f",
        }

    def test_duration_s(self):
        assert number_input_kwargs("duration_s", 180) == {
            "value": 180.0,
            "min_value": 0.0,
            "step": 1.0,
            "format": "%.1f",
        }

    def test_cost(self):
        assert number_input_kwargs("cost", 1.5) == {
            "value": 1.5,
            "min_value": 0.0,
            "step": 0.01,
            "format": "%.2f",
        }

    def test_categorical(self):
        assert number_input_kwargs("categorical", 2) == {
            "value": 2,
            "min_value": 1,
            "step": 1,
        }

    def test_categorical_uses_int_types(self):
        # Load-bearing: int value/step/min make st.number_input render an integer
        # spinner (no decimals) for num_bots/num_manual_resources.
        # `==` wouldn't catch a float regression here (2 == 2.0), so assert types.
        kwargs = number_input_kwargs("categorical", 2.0)
        assert type(kwargs["value"]) is int
        assert type(kwargs["min_value"]) is int
        assert type(kwargs["step"]) is int

    def test_float_kinds_coerce_int_value_to_float(self):
        # Mirror of test_categorical_uses_int_types: st.number_input raises on a
        # mixed int value + float min/step, so the float kinds must coerce an int
        # input to float. `==` wouldn't catch a dropped float() cast (50 == 50.0),
        # so assert the type after passing an INT input.
        for kind in ("percentage", "duration_s", "cost"):
            assert type(number_input_kwargs(kind, 50)["value"]) is float

    def test_unknown_kind_falls_back_to_value_only(self):
        # Out of the ParameterKind contract (hence the ignore) — exercises the
        # defensive default so the safety net stays covered.
        kwargs = number_input_kwargs("mystery", 7)  # type: ignore[arg-type]
        assert kwargs == {"value": 7.0}
