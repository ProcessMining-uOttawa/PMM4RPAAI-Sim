"""Plotly chart helpers for Panel 4 main-effects display."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from core.parameters import Parameter


def factor_label_map(params: list[Parameter]) -> dict[str, str]:
    """Map raw main_effects() factor IDs to human-readable Parameter labels.

    Parameter.id already carries the full column key used by main_effects()
    (e.g. "Fix Bug.pct_auto"). Returns {"Fix Bug.pct_auto": "Automation rate (%)", ...}.
    """
    return {p.id: p.label for p in params}


def _level_str(v: object) -> str:
    """Convert a level value to a display string without spurious '.0' suffixes."""
    try:
        f = float(v)  # type: ignore[arg-type]
        return str(int(f)) if f == int(f) else str(f)
    except (ValueError, TypeError):
        return str(v)


def main_effects_chart(
    me: pd.DataFrame,
    label_map: dict[str, str],
    metric_label: str,
) -> go.Figure:
    """Faceted line chart of factor-level means for one metric.

    Args:
        me: DataFrame from analysis.main_effects() — columns: factor, level, mean, sn.
        label_map: {raw_factor_id: display_label} from factor_label_map().
        metric_label: Y-axis title (e.g. "Cycle time (h)").
    """
    df = me.copy()
    df["factor"] = df["factor"].map(label_map).fillna(df["factor"])
    # Sort by numeric level before string conversion so categorical axis order
    # follows actual values, not the user's level-1/2/3 assignment order.
    df = df.sort_values(["factor", "level"])
    df["level"] = df["level"].apply(_level_str)

    wrap = 4
    fig = px.line(
        df,
        x="level",
        y="mean",
        facet_col="factor",
        facet_col_wrap=wrap,
        facet_row_spacing=0.2,
        markers=True,
        labels={"mean": metric_label, "level": "Level"},
    )
    fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
    n_rows = (df["factor"].nunique() + wrap - 1) // wrap
    fig.update_layout(
        height=n_rows * 280,
        margin={"t": 40, "b": 20, "l": 40, "r": 20},
        showlegend=False,
    )
    fig.update_xaxes(
        matches=None,
        type="category",
        categoryorder="trace",
        showticklabels=True,
        title_text="Level",
        range=[-0.5, 2.5],
    )
    fig.update_yaxes(matches=None)
    return fig
