"""Tests for ui/plots — factor_label_map and main_effects_chart."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from core.parameters import Parameter
from ui.plots import factor_label_map, main_effects_chart

# Parameter.id already carries the full "<target>.<bare_id>" key that
# main_effects() uses as factor column names — mirror real construction here.
_TARGET = "Act"


def _params() -> list[Parameter]:
    return [
        Parameter(id=f"{_TARGET}.pct_auto", label="Automation rate (%)", levels=[25, 50, 75], kind="percentage"),
        Parameter(id=f"{_TARGET}.num_bots", label="Bot pool size",        levels=[1, 2, 3],   kind="categorical"),
    ]


def _me() -> pd.DataFrame:
    rows = []
    for param_id, levels in [
        (f"{_TARGET}.pct_auto", [25, 50, 75]),
        (f"{_TARGET}.num_bots", [1, 2, 3]),
    ]:
        for level in levels:
            rows.append({
                "factor": param_id,
                "level": level,
                "mean": float(level),
                "sn": -10.0,
            })
    return pd.DataFrame(rows)


class TestFactorLabelMap:

    def test_maps_param_ids_to_labels(self):
        m = factor_label_map(_params())
        assert m == {
            f"{_TARGET}.pct_auto": "Automation rate (%)",
            f"{_TARGET}.num_bots": "Bot pool size",
        }

    def test_empty_params_returns_empty_map(self):
        assert factor_label_map([]) == {}


class TestMainEffectsChart:

    def test_returns_figure(self):
        fig = main_effects_chart(_me(), factor_label_map(_params()), "Cycle time (h)")
        assert isinstance(fig, go.Figure)

    def test_facet_annotations_use_labels(self):
        fig = main_effects_chart(_me(), factor_label_map(_params()), "Cycle time (h)")
        annotation_texts = {a.text for a in fig.layout.annotations}
        assert "Automation rate (%)" in annotation_texts
        assert "Bot pool size" in annotation_texts

    def test_facet_annotations_strip_factor_prefix(self):
        fig = main_effects_chart(_me(), factor_label_map(_params()), "Cycle time (h)")
        annotation_texts = {a.text for a in fig.layout.annotations}
        assert not any(t.startswith("factor=") for t in annotation_texts)

    def test_level_values_are_strings_without_dot_zero(self):
        fig = main_effects_chart(_me(), factor_label_map(_params()), "Cycle time (h)")
        for trace in fig.data:
            for x in trace.x:
                assert isinstance(x, str)
                assert not x.endswith(".0"), f"level {x!r} has spurious .0 suffix"

    def test_integer_levels_strip_decimal(self):
        me = pd.DataFrame([
            {"factor": f"{_TARGET}.pct_auto", "level": 25.0, "mean": 10.0, "sn": -5.0},
            {"factor": f"{_TARGET}.pct_auto", "level": 50.0, "mean": 12.0, "sn": -5.0},
            {"factor": f"{_TARGET}.pct_auto", "level": 75.0, "mean": 14.0, "sn": -5.0},
        ])
        fig = main_effects_chart(me, factor_label_map(_params()), "Cycle time (h)")
        assert list(fig.data[0].x) == ["25", "50", "75"]

    def test_unknown_factor_kept_as_raw_id(self):
        fig = main_effects_chart(_me(), {}, "Cycle time (h)")
        annotation_texts = {a.text for a in fig.layout.annotations}
        assert any("pct_auto" in t for t in annotation_texts)

    def test_yaxes_independent(self):
        fig = main_effects_chart(_me(), factor_label_map(_params()), "Cycle time (h)")
        assert fig.layout.yaxis.matches is None

    def test_xaxes_independent(self):
        fig = main_effects_chart(_me(), factor_label_map(_params()), "Cycle time (h)")
        assert fig.layout.xaxis.matches is None

    def test_height_scales_with_factor_count(self):
        # 2 factors → 1 row; 5 factors → 2 rows (facet_col_wrap=4)
        extra_ids = [
            (f"{_TARGET}.t_auto",    "Auto time"),
            (f"{_TARGET}.t_manual",  "Manual time"),
            (f"{_TARGET}.num_bots2", "Extra bots"),
        ]
        me_5 = _me()
        for param_id, _ in extra_ids:
            for level in [60, 120, 180]:
                me_5 = pd.concat([me_5, pd.DataFrame([{
                    "factor": param_id, "level": level,
                    "mean": float(level), "sn": -10.0,
                }])], ignore_index=True)
        extra_params = _params() + [
            Parameter(id=f"{_TARGET}.t_auto",    label="Auto time",   levels=[60, 120, 180], kind="duration_s"),
            Parameter(id=f"{_TARGET}.t_manual",  label="Manual time", levels=[60, 120, 180], kind="duration_s"),
            Parameter(id=f"{_TARGET}.num_bots2", label="Extra bots",  levels=[1, 2, 3],      kind="categorical"),
        ]
        fig_5 = main_effects_chart(me_5, factor_label_map(extra_params), "Cycle time (h)")
        fig_2 = main_effects_chart(_me(), factor_label_map(_params()), "Cycle time (h)")
        assert fig_5.layout.height > fig_2.layout.height
