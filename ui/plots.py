"""Plotly chart helpers for the Panel 5 Main effects tab."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from core.parameters import Parameter

_FACETS_PER_ROW = 4  # facets per row in the main-effects grid
_FACET_ROW_HEIGHT_PX = 280  # vertical px allotted per facet row


def factor_label_map(params: list[Parameter]) -> dict[str, str]:
    """Map raw main_effects() factor IDs to human-readable Parameter labels."""
    return {p.id: p.label for p in params}


def _level_str(level: float) -> str:
    """Render a factor level as a display string, dropping a spurious '.0'."""
    return str(int(level)) if level == int(level) else str(level)


def main_effects_chart(
    effects: pd.DataFrame,
    label_map: dict[str, str],
    metric_label: str,
) -> go.Figure:
    """Faceted line chart of factor-level means for one metric.

    Args:
        effects: main_effects() output — columns: factor, level, mean, sn.
        label_map: {raw_factor_id: display_label} from factor_label_map().
        metric_label: Y-axis title (e.g. "Cycle time (h)").
    """
    df = effects.copy()
    df["factor"] = df["factor"].map(label_map).fillna(df["factor"])
    # Sort by numeric level before string conversion so categorical axis order
    # follows actual values, not the user's level-1/2/3 assignment order.
    df = df.sort_values(["factor", "level"])
    df["level"] = df["level"].apply(_level_str)

    fig = px.line(
        df,
        x="level",
        y="mean",
        facet_col="factor",
        facet_col_wrap=_FACETS_PER_ROW,
        facet_row_spacing=0.2,
        # Wide enough for each facet's own y tick labels — the default 0.02 gap
        # would let inner-facet labels overlap the neighbouring plot area.
        facet_col_spacing=0.06,
        markers=True,
        labels={"mean": metric_label, "level": "Level"},
    )
    # px.line titles each facet "factor=<label>"; keep only the label after "=".
    fig.for_each_annotation(
        lambda annotation: annotation.update(text=annotation.text.split("=")[-1])
    )
    n_rows = (df["factor"].nunique() + _FACETS_PER_ROW - 1) // _FACETS_PER_ROW
    fig.update_layout(
        height=n_rows * _FACET_ROW_HEIGHT_PX,
        margin={"t": 40, "b": 20, "l": 40, "r": 20},
        showlegend=False,
    )
    fig.update_xaxes(
        matches=None,
        type="category",
        categoryorder="trace",
        showticklabels=True,
        title_text="Level",
        # 3 Taguchi levels sit at category indices 0/1/2; pad ±0.5 for symmetry.
        range=[-0.5, 2.5],
    )
    # matches=None makes every facet's scale independent, so each must show its
    # own tick labels — px hides them on non-left facets, and an unlabelled
    # private scale reads as shared (equal line heights imply equal values).
    fig.update_yaxes(matches=None, showticklabels=True)
    return fig
