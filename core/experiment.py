"""Taguchi 3-level OA designs + scenario generation."""
from __future__ import annotations
from .parameters import Parameter, Scenario


# Standard Taguchi orthogonal arrays for 3-level factors (0-indexed levels).
# L9 (3^4): up to 4 factors.
L9 = [
    [0,0,0,0],[0,1,1,1],[0,2,2,2],
    [1,0,1,2],[1,1,2,0],[1,2,0,1],
    [2,0,2,1],[2,1,0,2],[2,2,1,0],
]
# L18 (2^1 x 3^7): use only the seven 3-level columns (drop col 0 here).
L18 = [
    [0,0,0,0,0,0,0],[0,1,1,1,1,1,1],[0,2,2,2,2,2,2],
    [1,0,0,1,1,2,2],[1,1,1,2,2,0,0],[1,2,2,0,0,1,1],
    [2,0,1,0,2,1,2],[2,1,2,1,0,2,0],[2,2,0,2,1,0,1],
    [0,0,2,2,1,1,0],[0,1,0,0,2,2,1],[0,2,1,1,0,0,2],
    [1,0,2,0,1,2,1],[1,1,0,1,2,0,2],[1,2,1,2,0,1,0],
    [2,0,1,2,2,0,1],[2,1,2,0,0,1,2],[2,2,0,1,1,2,0],
]
# L27 (3^13): up to 13 factors. (Omitted body for brevity — generated on demand.)


def pick_array(n_factors: int):
    if n_factors <= 4:
        return "L9", L9, 4
    if n_factors <= 7:
        return "L18", L18, 7
    raise ValueError(f"Need an OA for {n_factors} 3-level factors (add L27).")


def build_scenarios(
    parameters: list[Parameter],
    transformation_id: str,
    target_activity: str,
) -> tuple[str, list[Scenario]]:
    name, array, max_cols = pick_array(len(parameters))
    scenarios = []
    for i, row in enumerate(array):
        vals = {p.id: p.levels[row[j]] for j, p in enumerate(parameters)}
        scenarios.append(Scenario(
            id=f"S{i+1:02d}",
            values=vals,
            transformation_id=transformation_id,
            target_activity=target_activity,
        ))
    return name, scenarios
