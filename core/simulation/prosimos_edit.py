"""Prosimos input-JSON mutation helpers — all schema knowledge lives here."""
from __future__ import annotations

from ..constants import KEY_RESOURCE_PROFILES, KEY_TASK_RESOURCE_DISTRIBUTION

# ── Prosimos input JSON: schema key names (only consumed within this module and
#    transformations.py — too coupled to put in constants.py) ─────────────────
KEY_RESOURCE_CALENDARS      = "resource_calendars"
KEY_GATEWAY_BRANCHING_PROBS = "gateway_branching_probabilities"


def _write_distribution(entry: dict, name: str, params: list) -> None:
    for r in entry["resources"]:
        r["distribution_name"]   = name
        r["distribution_params"] = params


def set_uniform(entry: dict, mean_s: float, jitter: float = 0.05) -> None:
    lo = max(0.0, mean_s * (1 - jitter))
    hi = mean_s * (1 + jitter)
    _write_distribution(entry, "uniform", [{"value": lo}, {"value": hi}])


def set_fixed(entry: dict, mean_s: float) -> None:
    _write_distribution(entry, "fix", [{"value": mean_s}])


def set_resource_amount(data: dict, resource_id: str, amount: int) -> None:
    for profile in data.get(KEY_RESOURCE_PROFILES, []):
        for resource in profile.get("resource_list", []):
            if resource.get("id") == resource_id:
                resource["amount"] = amount
                return


def ensure_calendar(data: dict, entry: dict) -> None:
    """Add entry to data[KEY_RESOURCE_CALENDARS] if no calendar with the same id exists."""
    calendars = data.setdefault(KEY_RESOURCE_CALENDARS, [])
    if not any(c.get("id") == entry["id"] for c in calendars):
        calendars.append(entry)


def upsert_resource_in_profile(data: dict, profile_id: str, profile_name: str,
                                resource_entry: dict) -> None:
    """Ensure a resource profile exists and append resource_entry to its resource_list."""
    profiles = data.setdefault(KEY_RESOURCE_PROFILES, [])
    profile = next((p for p in profiles if p.get("id") == profile_id), None)
    if profile is None:
        profile = {"id": profile_id, "name": profile_name, "resource_list": []}
        profiles.append(profile)
    profile.setdefault("resource_list", []).append(resource_entry)


def append_task_distribution(data: dict, entry: dict) -> None:
    """Append a task distribution entry to data[KEY_TASK_RESOURCE_DISTRIBUTION]."""
    data[KEY_TASK_RESOURCE_DISTRIBUTION].append(entry)


def add_gateway_probs(data: dict, gateway_id: str,
                      path_probs: dict[str, float]) -> None:
    """Append one gateway branching-probability entry to data[KEY_GATEWAY_BRANCHING_PROBS]."""
    gbp = data.setdefault(KEY_GATEWAY_BRANCHING_PROBS, [])
    gbp.append({
        "gateway_id": gateway_id,
        "probabilities": [
            {"path_id": path_id, "value": value}
            for path_id, value in path_probs.items()
        ],
    })
