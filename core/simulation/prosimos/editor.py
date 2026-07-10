"""Prosimos input-JSON mutation helpers — all schema knowledge lives here."""

from __future__ import annotations

from ...constants import KEY_RESOURCE_PROFILES, KEY_TASK_RESOURCE_DISTRIBUTION

# ── Prosimos input JSON: schema key names (only consumed within this module —
#    too coupled to put in constants.py) ─────────────────
KEY_RESOURCE_CALENDARS = "resource_calendars"
KEY_GATEWAY_BRANCHING_PROBS = "gateway_branching_probabilities"


def _write_distribution(
    task_dist: dict, distribution_name: str, distribution_params: list
) -> None:
    """Write the same distribution (name + params) onto every resource of a task entry."""
    for resource in task_dist["resources"]:
        resource["distribution_name"] = distribution_name
        resource["distribution_params"] = distribution_params


def set_uniform(task_dist: dict, mean_s: float, jitter: float = 0.05) -> None:
    """Set a uniform duration distribution (mean_s ± jitter) on a task's resources."""
    lower = max(0.0, mean_s * (1 - jitter))
    upper = mean_s * (1 + jitter)
    _write_distribution(task_dist, "uniform", [{"value": lower}, {"value": upper}])


def set_fixed(task_dist: dict, mean_s: float) -> None:
    """Set a fixed (deterministic) duration distribution on a task's resources."""
    _write_distribution(task_dist, "fix", [{"value": mean_s}])


def set_resource_amount(sim_params: dict, resource_id: str, amount: int) -> None:
    """Set the pool size (amount) of a resource by id; no-op if the id is absent."""
    for profile in sim_params.get(KEY_RESOURCE_PROFILES, []):
        for resource in profile.get("resource_list", []):
            if resource.get("id") == resource_id:
                resource["amount"] = amount
                return


def ensure_calendar(sim_params: dict, calendar: dict) -> None:
    """Add calendar to sim_params[KEY_RESOURCE_CALENDARS] if no entry shares its id."""
    calendars = sim_params.setdefault(KEY_RESOURCE_CALENDARS, [])
    if not any(existing.get("id") == calendar["id"] for existing in calendars):
        calendars.append(calendar)


def upsert_resource_in_profile(
    sim_params: dict, profile_id: str, profile_name: str, resource_entry: dict
) -> None:
    """Ensure a resource profile exists and append resource_entry to its resource_list."""
    profiles = sim_params.setdefault(KEY_RESOURCE_PROFILES, [])
    profile = next(
        (existing for existing in profiles if existing.get("id") == profile_id), None
    )
    if profile is None:
        profile = {"id": profile_id, "name": profile_name, "resource_list": []}
        profiles.append(profile)
    profile.setdefault("resource_list", []).append(resource_entry)


def append_task_distribution(sim_params: dict, task_dist: dict) -> None:
    """Append a task distribution entry to sim_params[KEY_TASK_RESOURCE_DISTRIBUTION]."""
    sim_params[KEY_TASK_RESOURCE_DISTRIBUTION].append(task_dist)


def add_gateway_probs(
    sim_params: dict, gateway_id: str, path_probs: dict[str, float]
) -> None:
    """Append one gateway branching-probability entry to sim_params[KEY_GATEWAY_BRANCHING_PROBS]."""
    branching_probs = sim_params.setdefault(KEY_GATEWAY_BRANCHING_PROBS, [])
    branching_probs.append(
        {
            "gateway_id": gateway_id,
            "probabilities": [
                {"path_id": path_id, "value": value}
                for path_id, value in path_probs.items()
            ],
        }
    )
