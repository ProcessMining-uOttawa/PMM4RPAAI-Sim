"""Read-only helpers for querying Prosimos input JSON."""

from __future__ import annotations
from collections import Counter
from dataclasses import dataclass

from ...constants import KEY_TASK_RESOURCE_DISTRIBUTION, KEY_RESOURCE_PROFILES


@dataclass
class ResourceSelectorConfig:
    """Classification of a task's resources for the UI resource selector."""

    selectable: list[dict]  # [{id, name}] — resources the user can choose from
    frozen: list[dict]  # [{id, name}] — shared resources (displayed but not pickable)
    fallback_pool_size: (
        int | None
    )  # pool size shown read-only when all resources are shared


def task_resources(prosimos_json: dict, task_id: str) -> list[dict]:
    """Return [{id, name}] for resources assigned to task_id, in assignment order."""
    name_by_id = {
        resource["id"]: resource.get("name", resource["id"])
        for profile in prosimos_json.get(KEY_RESOURCE_PROFILES, [])
        for resource in profile.get("resource_list", [])
    }
    for entry in prosimos_json.get(KEY_TASK_RESOURCE_DISTRIBUTION, []):
        if entry.get("task_id") == task_id:
            return [
                {
                    "id": resource["resource_id"],
                    "name": name_by_id.get(
                        resource["resource_id"], resource["resource_id"]
                    ),
                }
                for resource in entry.get("resources", [])
            ]
    return []


def shared_resource_ids(prosimos_json: dict) -> set[str]:
    """Return resource IDs that appear in more than one task's distribution entry."""
    counts: Counter = Counter(
        resource["resource_id"]
        for entry in prosimos_json.get(KEY_TASK_RESOURCE_DISTRIBUTION, [])
        for resource in entry.get("resources", [])
    )
    return {rid for rid, count in counts.items() if count > 1}


def resource_pool_size(prosimos_json: dict, resource_id: str) -> int | None:
    """Return the current pool size (amount) for a resource, or None if not found."""
    for profile in prosimos_json.get(KEY_RESOURCE_PROFILES, []):
        for resource in profile.get("resource_list", []):
            if resource.get("id") == resource_id:
                return int(resource.get("amount", 1))
    return None


def resource_selector_config(
    prosimos_json: dict, task_id: str
) -> ResourceSelectorConfig:
    """Classify task resources into selectable vs. shared-frozen.

    Returns a config the UI can render directly; no domain decisions need to
    live in app.py.
    """
    resources = task_resources(prosimos_json, task_id)
    if len(resources) <= 1:
        return ResourceSelectorConfig(
            selectable=resources, frozen=[], fallback_pool_size=None
        )
    shared = shared_resource_ids(prosimos_json)
    selectable: list[dict] = []
    frozen: list[dict] = []
    for resource in resources:
        if resource["id"] in shared:
            frozen.append(resource)
        else:
            selectable.append(resource)
    fallback_pool_size: int | None = None
    if not selectable:
        fallback_pool_size = resource_pool_size(prosimos_json, resources[0]["id"])
    return ResourceSelectorConfig(
        selectable=selectable, frozen=frozen, fallback_pool_size=fallback_pool_size
    )


def task_mean_duration_s(prosimos_json: dict, task_id: str) -> float | None:
    """Return the average mean duration (over resources) for a task, or None."""
    for entry in prosimos_json.get(KEY_TASK_RESOURCE_DISTRIBUTION, []):
        if entry.get("task_id") != task_id:
            continue
        means = []
        for resource in entry.get("resources", []):
            dn = resource.get("distribution_name", "")
            params = [p["value"] for p in resource.get("distribution_params", [])]
            if dn == "uniform" and len(params) == 2:
                means.append((params[0] + params[1]) / 2)
            elif dn in ("fix", "fixed") and len(params) == 1:
                means.append(params[0])
            elif dn in ("expon", "exponential") and len(params) >= 1:
                means.append(params[0])
            elif dn in ("norm", "normal") and len(params) >= 1:
                means.append(params[0])
        if means:
            return sum(means) / len(means)
    return None
