"""Taguchi 3-level OA designs + scenario generation."""

from __future__ import annotations
from .parameters import Parameter, Scenario

# Standard Taguchi orthogonal arrays for 3-level factors (0-indexed levels).
# L9 (3^4): up to 4 factors.
L9 = [
    [0, 0, 0, 0],
    [0, 1, 1, 1],
    [0, 2, 2, 2],
    [1, 0, 1, 2],
    [1, 1, 2, 0],
    [1, 2, 0, 1],
    [2, 0, 2, 1],
    [2, 1, 0, 2],
    [2, 2, 1, 0],
]
# L18 (2^1 x 3^7): use only the seven 3-level columns (drop col 0 here).
L18 = [
    [0, 0, 0, 0, 0, 0, 0],
    [0, 1, 1, 1, 1, 1, 1],
    [0, 2, 2, 2, 2, 2, 2],
    [1, 0, 0, 1, 1, 2, 2],
    [1, 1, 1, 2, 2, 0, 0],
    [1, 2, 2, 0, 0, 1, 1],
    [2, 0, 1, 0, 2, 1, 2],
    [2, 1, 2, 1, 0, 2, 0],
    [2, 2, 0, 2, 1, 0, 1],
    [0, 0, 2, 2, 1, 1, 0],
    [0, 1, 0, 0, 2, 2, 1],
    [0, 2, 1, 1, 0, 0, 2],
    [1, 0, 1, 2, 0, 2, 1],
    [1, 1, 2, 0, 1, 0, 2],
    [1, 2, 0, 1, 2, 1, 0],
    [2, 0, 2, 1, 2, 0, 1],
    [2, 1, 0, 2, 0, 1, 2],
    [2, 2, 1, 0, 1, 2, 0],
]


def pick_array(n_factors: int):
    if n_factors < 0:
        raise ValueError(f"n_factors must be non-negative; got {n_factors}.")
    if n_factors == 0:
        return "L1", [[]], 0
    if n_factors <= 4:
        return "L9", L9, 4
    if n_factors <= 7:
        return "L18", L18, 7
    raise ValueError(f"Need an OA for {n_factors} 3-level factors (max supported: 7).")


# Rows per array, for callers reporting how far a design was reduced.
ARRAY_SIZES = {"L1": 1, "L9": len(L9), "L18": len(L18)}


def is_design_constant(parameter: Parameter) -> bool:
    """True when the factor contributes no variation: frozen, or user-pinned
    (all three levels equal). Two-of-three equal — the Taguchi dummy-level
    technique, a 2:1 exposure weighting — keeps the factor in the design."""
    return parameter.frozen or len(set(parameter.levels)) == 1


def build_scenarios(
    parameters: list[Parameter],
    transformation_id: str,
    target_activity: str,
) -> tuple[str, list[Scenario]]:
    """One Scenario per OA row over the varying factors, duplicates removed.

    Design constants are excluded from the array (shrinking it via pick_array)
    and injected into every scenario at their single value. Rows made
    identical by heavy pinning are dropped first-occurrence-wins; ids keep
    their OA row numbers, so gaps mark removed duplicates.
    """
    active = [p for p in parameters if not is_design_constant(p)]
    constant = [p for p in parameters if is_design_constant(p)]

    name, array, _ = pick_array(len(active))
    scenarios = []
    seen: set[tuple] = set()
    for i, row in enumerate(array):
        vals = {p.id: p.levels[row[j]] for j, p in enumerate(active)}
        for p in constant:
            vals[p.id] = p.levels[0]
        key = tuple(sorted(vals.items()))
        if key in seen:
            continue
        seen.add(key)
        scenarios.append(
            Scenario(
                id=f"S{i + 1:02d}",
                values=vals,
                transformation_id=transformation_id,
                target_activity=target_activity,
            )
        )
    return name, scenarios
