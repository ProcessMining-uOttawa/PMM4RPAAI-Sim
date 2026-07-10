"""Tests for ui/plots — factor_label_map and main_effects_chart."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from core.parameters import Parameter
from ui.plots import factor_label_map, main_effects_chart


def _params() -> list[Parameter]:
    return [
        Parameter(
            id="pct_auto",
            label="Automation rate (%)",
            levels=[25, 50, 75],
            kind="percentage",
        ),
        Parameter(
            id="num_bots", label="Bot pool size", levels=[1, 2, 3], kind="categorical"
        ),
    ]


def _me(params: list[Parameter] | None = None) -> pd.DataFrame:
    """Build a minimal main_effects() DataFrame derived from _params()."""
    if params is None:
        params = _params()
    rows = []
    for p in params:
        for level in p.levels:
            rows.append(
                {"factor": p.id, "level": level, "mean": float(level), "sn": -10.0}
            )
    return pd.DataFrame(rows)


def _fig() -> go.Figure:
    return main_effects_chart(_me(), factor_label_map(_params()), "Cycle time (h)")


class TestFactorLabelMap:
    def test_maps_param_ids_to_labels(self):
        m = factor_label_map(_params())
        assert m == {
            "pct_auto": "Automation rate (%)",
            "num_bots": "Bot pool size",
        }

    def test_empty_params_returns_empty_map(self):
        assert factor_label_map([]) == {}


class TestMainEffectsChart:
    def test_returns_figure(self):
        assert isinstance(_fig(), go.Figure)

    def test_facet_annotations_use_labels(self):
        annotation_texts = {a.text for a in _fig().layout.annotations}
        assert "Automation rate (%)" in annotation_texts
        assert "Bot pool size" in annotation_texts

    def test_facet_annotations_strip_factor_prefix(self):
        annotation_texts = {a.text for a in _fig().layout.annotations}
        assert not any(t.startswith("factor=") for t in annotation_texts)

    def test_level_values_are_strings_without_dot_zero(self):
        for trace in _fig().data:
            for x in trace.x:
                assert isinstance(x, str)
                assert not x.endswith(".0"), f"level {x!r} has spurious .0 suffix"

    def test_integer_levels_strip_decimal(self):
        me = pd.DataFrame(
            [
                {"factor": "pct_auto", "level": 25.0, "mean": 10.0, "sn": -5.0},
                {"factor": "pct_auto", "level": 50.0, "mean": 12.0, "sn": -5.0},
                {"factor": "pct_auto", "level": 75.0, "mean": 14.0, "sn": -5.0},
            ]
        )
        fig = main_effects_chart(me, factor_label_map(_params()), "Cycle time (h)")
        assert list(fig.data[0].x) == ["25", "50", "75"]

    def test_levels_sorted_numeric_ascending_not_row_order(self):
        # Rows arrive scrambled AND lexical != numeric here: lexical sort gives
        # ["100", "1000", "500"], row order gives ["500", "100", "1000"], only
        # numeric-ascending gives ["100", "500", "1000"]. This pins the
        # df.sort_values(["factor", "level"]) axis-order fix — deleting it (row
        # order) or sorting strings (lexical) both fail.
        me = pd.DataFrame(
            [
                {"factor": "num_cases", "level": 500.0, "mean": 10.0, "sn": -5.0},
                {"factor": "num_cases", "level": 100.0, "mean": 12.0, "sn": -5.0},
                {"factor": "num_cases", "level": 1000.0, "mean": 14.0, "sn": -5.0},
            ]
        )
        fig = main_effects_chart(me, factor_label_map(_params()), "Cycle time (h)")
        assert list(fig.data[0].x) == ["100", "500", "1000"]

    def test_all_facet_xaxes_are_category(self):
        # Explicit categorical axis stops Plotly treating numeric-looking level
        # strings as a linear axis (auto ticks at round numbers, not data points).
        # _fig() has two factors -> two facets -> two x-axes; every one must be
        # categorical, so a regression that set it on xaxis alone would be caught.
        axes = list(_fig().select_xaxes())
        assert len(axes) > 1
        assert all(ax.type == "category" for ax in axes)

    def test_unknown_factor_kept_as_raw_id(self):
        annotation_texts = {
            a.text
            for a in main_effects_chart(_me(), {}, "Cycle time (h)").layout.annotations
        }
        assert any("pct_auto" in t for t in annotation_texts)

    def test_yaxes_independent(self):
        assert _fig().layout.yaxis.matches is None

    def test_xaxes_independent(self):
        assert _fig().layout.xaxis.matches is None

    def test_height_scales_with_factor_count(self):
        # 2 factors → 1 row; 5 factors → 2 rows (facet_col_wrap=4)
        extra_params = _params() + [
            Parameter(
                id="t_auto", label="Auto time", levels=[60, 120, 180], kind="duration_s"
            ),
            Parameter(
                id="t_manual",
                label="Manual time",
                levels=[60, 120, 180],
                kind="duration_s",
            ),
            Parameter(
                id="num_bots2", label="Extra bots", levels=[1, 2, 3], kind="categorical"
            ),
        ]
        fig_5 = main_effects_chart(
            _me(extra_params), factor_label_map(extra_params), "Cycle time (h)"
        )
        assert fig_5.layout.height > _fig().layout.height
