"""Calendar-aware time accounting for Prosimos event logs.

Joins a Prosimos params JSON (resource calendars + cost rates) against an event
log to derive per-event working seconds and per-event cost — the quantities the
stats CSV reports but the event log does not carry directly. Prosimos charges
cost on a resource's *working* time only (``cost_per_hour × processing_time``,
where processing time is the sampled duration threaded through the resource
calendar), so the naive ``(end − start) × rate`` over-counts every task that
sits paused across an off-shift gap. Intersecting each event's ``[start, end)``
with its resource's weekly calendar recovers Prosimos's number (verified to the
cent on real runs).

Mirrors the sibling schema modules: ``editor.py`` mutates the params JSON,
``query.py`` reads scalars out of it, and this module *joins* it against an
event-log DataFrame — a distinct concern with its own home.

Calendar format precondition: every ``time_periods`` entry lies within a single
day (``endTime > beginTime``). Overnight / midnight-crossing shifts (a night
shift, a 24/7 process) would need cross-day interval handling and are rejected
loudly rather than silently miscounted; the calendars Simod discovers here are
day-bounded (daytime human shifts; a full-day bot calendar).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from ...constants import KEY_RESOURCE_CALENDARS, KEY_RESOURCE_PROFILES

# Prosimos names the instances of a pool with amount > 1 "<base>_0", "<base>_1", …
# in the event log, while the params carry only the base. amount == 1 pools (every
# Simod-discovered human, and num_bots == 1) keep the base name unsuffixed.
_INSTANCE_SUFFIX = re.compile(r"_\d+$")

_WEEKDAYS = {
    "MONDAY": 0,
    "TUESDAY": 1,
    "WEDNESDAY": 2,
    "THURSDAY": 3,
    "FRIDAY": 4,
    "SATURDAY": 5,
    "SUNDAY": 6,
}
_EPOCH = pd.Timestamp("1970-01-01", tz="UTC")
_ARRIVAL_CALENDAR_KEY = (
    "arrival_time_calendar"  # top-level params section (this module only)
)


def _epoch_seconds(column: pd.Series) -> np.ndarray:
    """Datetime column → epoch-seconds float array; naive input is read as UTC."""
    if column.dt.tz is None:
        column = column.dt.tz_localize("UTC")
    return (column - _EPOCH).dt.total_seconds().to_numpy()


def _seconds_of_day(hms: str) -> float:
    """Seconds since midnight for a ``HH:MM:SS[.ffffff]`` calendar time string."""
    hours, minutes, seconds = hms.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Union overlapping/adjacent ``(begin, end)`` intervals, sorted by begin."""
    merged: list[tuple[float, float]] = []
    for begin, end in sorted(intervals):
        if merged and begin <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((begin, end))
    return merged


class WeeklyCalendar:
    """A resource's weekly availability, as within-day open intervals per weekday.

    ``by_day[weekday]`` is a list of ``(begin_s, end_s)`` seconds-since-midnight
    pairs (Monday = 0). A ``from``→``to`` weekday range in a period applies the
    same within-day window to each weekday in the (wrapping) range.
    """

    def __init__(self, time_periods: list[dict]) -> None:
        raw: dict[int, list[tuple[float, float]]] = {}
        for period in time_periods:
            begin = _seconds_of_day(period["beginTime"])
            end = _seconds_of_day(period["endTime"])
            if end <= begin:
                raise ValueError(
                    "calendar period is not within a single day "
                    f"(overnight/midnight-crossing shifts unsupported): {period}"
                )
            day = _WEEKDAYS[period["from"]]
            last = _WEEKDAYS[period["to"]]
            while True:
                raw.setdefault(day, []).append((begin, end))
                if day == last:
                    break
                day = (day + 1) % 7
        # Merge overlapping/adjacent periods into the availability union. Prosimos
        # charges working time on the union (a resource is "on" once, not twice,
        # for an overlap), and the cumulative-work searchsorted relies on
        # non-overlapping intervals — discovered calendars can carry overlapping
        # periods on one weekday.
        self.by_day = {day: _merge_intervals(periods) for day, periods in raw.items()}

    def is_working_time(self, ts: pd.Timestamp) -> bool:
        """True when ``ts`` falls inside an open interval (``[begin, end)``)."""
        sod = ts.hour * 3600 + ts.minute * 60 + ts.second + ts.microsecond / 1e6
        return any(
            begin <= sod < end for begin, end in self.by_day.get(ts.weekday(), [])
        )


class _WorkClock:
    """Cumulative working-seconds for one weekly calendar over an absolute span.

    Materialises the calendar's open intervals as absolute ``[start, end)`` epoch
    seconds covering ``[t0, t1]``, then answers ``work_before(t)`` — total open
    seconds before ``t`` — for a whole array of query times via two searchsorted
    steps. ``event_work = work_before(end) − work_before(start)``.
    """

    def __init__(self, calendar: WeeklyCalendar, t0: float, t1: float) -> None:
        starts: list[float] = []
        ends: list[float] = []
        day = datetime.fromtimestamp(t0, tz=timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        while day.timestamp() <= t1:  # includes t1's own day (its midnight ≤ t1)
            base = day.timestamp()
            for begin, end in calendar.by_day.get(day.weekday(), []):
                starts.append(base + begin)
                ends.append(base + end)
            day += timedelta(days=1)
        order = np.argsort(starts, kind="stable")
        self._starts = np.asarray(starts, dtype=float)[order]
        self._ends = np.asarray(ends, dtype=float)[order]
        # cum[i] = open seconds fully before interval i (cum[0] = 0).
        self._cum = np.concatenate([[0.0], np.cumsum(self._ends - self._starts)])

    def work_before(self, times: np.ndarray) -> np.ndarray:
        """Open seconds before each time in ``times`` (0 when before all intervals)."""
        out = np.zeros(len(times), dtype=float)
        if len(self._starts) == 0:
            return out
        idx = np.searchsorted(self._starts, times, side="right") - 1
        valid = idx >= 0
        vi = idx[valid]
        out[valid] = (
            self._cum[vi] + np.minimum(times[valid], self._ends[vi]) - self._starts[vi]
        )
        return out


def _resource_maps(
    params: dict,
) -> tuple[dict[str, float], dict[str, WeeklyCalendar | None]]:
    """Map each resource key → (cost_per_hour, WeeklyCalendar).

    Keyed by BOTH id and name because the event log's ``resource`` column carries
    the name, which equals the id for Simod-discovered humans but not for the
    transform's bot resource (``node_…_bot_resource`` / ``"Auto … bot"``). A name
    shared by two resources with different rate/calendar is ambiguous and raises.
    Pooled instances (``"<name>_<i>"``) are resolved to their base by ``_lookup``.
    """
    calendar_by_id = {
        cal["id"]: WeeklyCalendar(cal["time_periods"])
        for cal in params.get(KEY_RESOURCE_CALENDARS, [])
    }
    rate: dict[str, float] = {}
    calendar: dict[str, WeeklyCalendar | None] = {}
    for profile in params.get(KEY_RESOURCE_PROFILES, []):
        for resource in profile.get("resource_list", []):
            resource_rate = float(resource.get("cost_per_hour", 0.0))
            resource_cal = calendar_by_id.get(resource.get("calendar"))
            for key in (resource.get("id"), resource.get("name")):
                if key is None:
                    continue
                if key in rate and (
                    rate[key] != resource_rate or calendar.get(key) is not resource_cal
                ):
                    raise ValueError(
                        f"resource key {key!r} maps to conflicting rate/calendar"
                    )
                rate[key] = resource_rate
                calendar[key] = resource_cal
    return rate, calendar


def _lookup(
    resource_name: str,
    rate_by_res: dict[str, float],
    calendar_by_res: dict[str, WeeklyCalendar | None],
) -> tuple[float, WeeklyCalendar] | None:
    """(rate, calendar) for a log resource name, or None if it has no usable calendar.

    Tries the name as-is, then — for a pooled instance ``"<base>_<i>"`` — its base.
    None covers both an unknown resource and one whose calendar id was unmapped;
    the caller raises for either when the resource did nonzero-duration work.
    """
    key = (
        resource_name
        if resource_name in calendar_by_res
        else _INSTANCE_SUFFIX.sub("", resource_name)
    )
    calendar = calendar_by_res.get(key)
    return (rate_by_res[key], calendar) if calendar is not None else None


def event_costs(task_log: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Per-event working seconds and cost, row-aligned to ``task_log``.

    ``task_log`` is the event log with the non-task (event) rows already removed
    (they carry no resource). Columns ``start_time``/``end_time`` must be parsed
    datetimes and ``resource`` the resource name. Returns a DataFrame indexed like
    ``task_log`` with ``work_s`` (calendar-intersected seconds) and ``cost``
    (``work_s / 3600 × cost_per_hour``).

    Raises ``ValueError`` for a nonzero-duration event whose resource is absent
    from the params (a silent zero-cost fallback is exactly the class of error a
    trust pipeline must not have); a zero-duration unknown-resource row costs 0.
    """
    work = np.zeros(len(task_log), dtype=float)
    cost = np.zeros(len(task_log), dtype=float)
    if len(task_log) == 0:
        return pd.DataFrame({"work_s": work, "cost": cost}, index=task_log.index)

    rate_by_res, cal_by_res = _resource_maps(params)
    starts = _epoch_seconds(task_log["start_time"])
    ends = _epoch_seconds(task_log["end_time"])
    resources = task_log["resource"].to_numpy()
    t0, t1 = float(starts.min()), float(ends.max())

    for resource_name, positions in (
        pd.Series(resources).groupby(resources).indices.items()
    ):
        resolved = _lookup(resource_name, rate_by_res, cal_by_res)
        if resolved is None:
            if (ends[positions] - starts[positions] > 0).any():
                raise ValueError(
                    f"resource {resource_name!r} appears in the event log but has "
                    "no cost calendar (absent from the params resource profiles, or "
                    "its calendar id is unmapped)"
                )
            continue  # zero-duration only → work/cost stay 0
        rate, calendar = resolved
        clock = _WorkClock(calendar, t0, t1)
        seconds = clock.work_before(ends[positions]) - clock.work_before(
            starts[positions]
        )
        work[positions] = seconds
        cost[positions] = seconds / 3600.0 * rate
    return pd.DataFrame({"work_s": work, "cost": cost}, index=task_log.index)


def arrival_calendar(params: dict) -> WeeklyCalendar:
    """The process arrival calendar (windows in which cases may arrive)."""
    return WeeklyCalendar(params.get(_ARRIVAL_CALENDAR_KEY, []))
