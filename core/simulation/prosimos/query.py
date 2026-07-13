"""Read-only helpers for querying Prosimos input JSON."""

from __future__ import annotations
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass

from ...constants import KEY_TASK_RESOURCE_DISTRIBUTION, KEY_RESOURCE_PROFILES


@dataclass
class ResourceSelectorConfig:
    """Classification of a task's resources for the UI resource selector."""

    # resources the user can choose from, as [{id, name}]
    selectable: list[dict]
    # shared resources: displayed but not pickable, as [{id, name}]
    frozen: list[dict]
    # pool size shown read-only when all resources are shared (else None)
    fallback_pool_size: int | None


# ── Private JSON navigation ────────────────────────────────────────────────────


def _all_profile_resources(prosimos_json: dict) -> Iterator[dict]:
    """Yield every resource dict across all resource profiles."""
    for profile in prosimos_json.get(KEY_RESOURCE_PROFILES, []):
        yield from profile.get("resource_list", [])


def _task_distribution(prosimos_json: dict, task_id: str) -> dict | None:
    """Return the task_resource_distribution entry for task_id, or None."""
    for entry in prosimos_json.get(KEY_TASK_RESOURCE_DISTRIBUTION, []):
        if entry.get("task_id") == task_id:
            return entry
    return None


def _distribution_mean(resource: dict) -> float | None:
    """Mean duration of one resource's distribution, or None if unrecognised."""
    distribution_name = resource.get("distribution_name", "")
    params = [param["value"] for param in resource.get("distribution_params", [])]
    if distribution_name == "uniform" and len(params) == 2:
        return (params[0] + params[1]) / 2
    # Prosimos (pix_framework) stores the empirical mean as the first param for every
    # distribution Simod emits except uniform: fix [mean], expon [mean, min, max],
    # norm [mean, std, min, max], lognorm/gamma [mean, var, min, max]. (triang is in
    # the enum but the fitter never emits it, so it stays unhandled → None.)
    mean_first = {
        "fix",
        "fixed",
        "expon",
        "exponential",
        "norm",
        "normal",
        "lognorm",
        "lognormal",
        "log_normal",
        "gamma",
    }
    if distribution_name in mean_first and params:
        return params[0]
    return None


# ── Public queries ─────────────────────────────────────────────────────────────


def task_resources(prosimos_json: dict, task_id: str) -> list[dict]:
    """Return [{id, name}] for resources assigned to task_id, in assignment order."""
    entry = _task_distribution(prosimos_json, task_id)
    if entry is None:
        return []
    name_by_id = {
        resource["id"]: resource.get("name", resource["id"])
        for resource in _all_profile_resources(prosimos_json)
    }
    return [
        {
            "id": resource["resource_id"],
            "name": name_by_id.get(resource["resource_id"], resource["resource_id"]),
        }
        for resource in entry.get("resources", [])
    ]


def shared_resource_ids(prosimos_json: dict) -> set[str]:
    """Return resource IDs that appear in more than one task's distribution entry."""
    counts: Counter = Counter(
        resource["resource_id"]
        for entry in prosimos_json.get(KEY_TASK_RESOURCE_DISTRIBUTION, [])
        for resource in entry.get("resources", [])
    )
    return {resource_id for resource_id, count in counts.items() if count > 1}


def resource_pool_size(prosimos_json: dict, resource_id: str) -> int | None:
    """Return the current pool size (amount) for a resource, or None if not found."""
    for resource in _all_profile_resources(prosimos_json):
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
    if not resources:
        # Empty task only. A single resource intentionally falls through to the
        # partition below, which selects it if unshared and freezes it if shared
        # — a lone shared resource must not be pickable (it drives another task).
        return ResourceSelectorConfig(
            selectable=resources, frozen=[], fallback_pool_size=None
        )
    shared = shared_resource_ids(prosimos_json)
    selectable = [resource for resource in resources if resource["id"] not in shared]
    frozen = [resource for resource in resources if resource["id"] in shared]
    fallback_pool_size: int | None = None
    if not selectable:
        fallback_pool_size = resource_pool_size(prosimos_json, resources[0]["id"])
    return ResourceSelectorConfig(
        selectable=selectable, frozen=frozen, fallback_pool_size=fallback_pool_size
    )


def task_mean_duration_s(prosimos_json: dict, task_id: str) -> float | None:
    """Return the average mean duration (over resources) for a task, or None."""
    entry = _task_distribution(prosimos_json, task_id)
    if entry is None:
        return None
    means = []
    for resource in entry.get("resources", []):
        mean = _distribution_mean(resource)
        if mean is not None:
            means.append(mean)
    return sum(means) / len(means) if means else None
