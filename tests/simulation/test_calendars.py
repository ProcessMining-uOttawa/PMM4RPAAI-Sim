"""Unit tests for the calendar-aware cost/working-time engine."""

from __future__ import annotations

import pandas as pd
import pytest

from core.simulation.prosimos import calendars
from core.simulation.prosimos.calendars import WeeklyCalendar, event_costs

# A 9-to-5, Monday-to-Friday calendar (exercises from->to day-range expansion).
NINE_TO_FIVE = [
    {"from": "MONDAY", "to": "FRIDAY", "beginTime": "09:00:00", "endTime": "17:00:00"}
]


def _ts(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz="UTC")


def _params(
    calendar_periods: list[dict] = NINE_TO_FIVE,
    resources: list[dict] | None = None,
) -> dict:
    """Minimal params with one resource 'Clerk' at $10/hr on the given calendar."""
    if resources is None:
        resources = [
            {"id": "Clerk", "name": "Clerk", "cost_per_hour": 10, "calendar": "cal"}
        ]
    return {
        "resource_calendars": [{"id": "cal", "time_periods": calendar_periods}],
        "resource_profiles": [{"resource_list": resources}],
        "arrival_time_calendar": NINE_TO_FIVE,
    }


def _log(rows: list[tuple[str, str, str]]) -> pd.DataFrame:
    """rows: (resource, start_iso, end_iso). activity/case_id filled trivially."""
    return pd.DataFrame(
        {
            "case_id": range(len(rows)),
            "activity": ["T"] * len(rows),
            "start_time": [_ts(s) for _, s, _ in rows],
            "end_time": [_ts(e) for _, _, e in rows],
            "resource": [r for r, _, _ in rows],
        }
    )


def _work(rows: list[tuple[str, str, str]], params: dict | None = None) -> list[float]:
    log = _log(rows)
    return event_costs(log, params or _params())["work_s"].tolist()


# ── WeeklyCalendar ─────────────────────────────────────────────────────────────


class TestWeeklyCalendar:
    def test_is_working_time_inside_and_outside(self):
        cal = WeeklyCalendar(NINE_TO_FIVE)
        assert cal.is_working_time(_ts("2025-01-06 10:00:00"))  # Monday 10:00
        assert not cal.is_working_time(_ts("2025-01-06 08:00:00"))  # Monday 08:00
        assert not cal.is_working_time(_ts("2025-01-04 10:00:00"))  # Saturday

    def test_is_working_time_half_open_interval(self):
        cal = WeeklyCalendar(NINE_TO_FIVE)
        assert cal.is_working_time(_ts("2025-01-06 09:00:00"))  # begin included
        assert not cal.is_working_time(_ts("2025-01-06 17:00:00"))  # end excluded

    def test_day_range_expands(self):
        cal = WeeklyCalendar(NINE_TO_FIVE)
        assert set(cal.by_day) == {0, 1, 2, 3, 4}  # Mon..Fri, not Sat/Sun

    def test_midnight_crossing_raises(self):
        with pytest.raises(ValueError, match="within a single day"):
            WeeklyCalendar(
                [
                    {
                        "from": "MONDAY",
                        "to": "MONDAY",
                        "beginTime": "22:00:00",
                        "endTime": "02:00:00",
                    }
                ]
            )

    def test_overlapping_periods_merge_to_union(self):
        cal = WeeklyCalendar(
            [
                {
                    "from": "MONDAY",
                    "to": "MONDAY",
                    "beginTime": "09:00:00",
                    "endTime": "12:00:00",
                },
                {
                    "from": "MONDAY",
                    "to": "MONDAY",
                    "beginTime": "11:00:00",
                    "endTime": "15:00:00",
                },
            ]
        )
        assert cal.by_day[0] == [(9 * 3600, 15 * 3600)]  # one merged window


# ── event_costs working-seconds ────────────────────────────────────────────────


class TestWorkingSeconds:
    def test_event_inside_one_interval(self):
        # Monday 10:00-12:00 = 2h fully inside 9-17.
        assert _work([("Clerk", "2025-01-06 10:00:00", "2025-01-06 12:00:00")]) == [
            7200.0
        ]

    def test_starts_before_shift(self):
        # Monday 08:00-10:00 → only 09:00-10:00 counts.
        assert _work([("Clerk", "2025-01-06 08:00:00", "2025-01-06 10:00:00")]) == [
            3600.0
        ]

    def test_ends_on_interval_edge(self):
        # Monday 16:00-17:00 → full hour up to the excluded-end boundary.
        assert _work([("Clerk", "2025-01-06 16:00:00", "2025-01-06 17:00:00")]) == [
            3600.0
        ]

    def test_spans_overnight_gap(self):
        # Monday 16:00 -> Tuesday 10:00: Mon 16-17 (1h) + Tue 9-10 (1h) = 2h.
        assert _work([("Clerk", "2025-01-06 16:00:00", "2025-01-07 10:00:00")]) == [
            7200.0
        ]

    def test_spans_weekend(self):
        # Friday 16:00 -> Monday 10:00: Fri 16-17 (1h) + Mon 9-10 (1h) = 2h (Sat/Sun off).
        assert _work([("Clerk", "2025-01-10 16:00:00", "2025-01-13 10:00:00")]) == [
            7200.0
        ]

    def test_multi_week_span(self):
        # Mon 10:00 -> Mon+1week 10:00: 5 full weekdays (9-17 = 8h) minus the first
        # day's 9-10 already elapsed + the last day's 10-17 not yet: 4*8h + (17-10) + (10-9).
        # = 32h + 7h + 1h = 40h.
        assert _work([("Clerk", "2025-01-06 10:00:00", "2025-01-13 10:00:00")]) == [
            40 * 3600.0
        ]

    def test_zero_duration_event(self):
        assert _work([("Clerk", "2025-01-06 10:00:00", "2025-01-06 10:00:00")]) == [0.0]

    def test_event_entirely_off_shift(self):
        # Saturday all day → 0 working seconds.
        assert _work([("Clerk", "2025-01-04 10:00:00", "2025-01-04 14:00:00")]) == [0.0]

    def test_overlapping_calendar_counts_union_once(self):
        params = _params(
            calendar_periods=[
                {
                    "from": "MONDAY",
                    "to": "MONDAY",
                    "beginTime": "09:00:00",
                    "endTime": "13:00:00",
                },
                {
                    "from": "MONDAY",
                    "to": "MONDAY",
                    "beginTime": "12:00:00",
                    "endTime": "17:00:00",
                },
            ]
        )
        # Monday 09:00-17:00 spans the union once = 8h, not 8h + the 12-13 overlap.
        assert _work(
            [("Clerk", "2025-01-06 09:00:00", "2025-01-06 17:00:00")], params
        ) == [8 * 3600.0]


# ── cost + resource join ───────────────────────────────────────────────────────


class TestCost:
    def test_cost_is_work_hours_times_rate(self):
        # 2h at $10/hr = $20.
        cost = event_costs(
            _log([("Clerk", "2025-01-06 10:00:00", "2025-01-06 12:00:00")]), _params()
        )["cost"].tolist()
        assert cost == [20.0]

    def test_string_cost_per_hour_parsed(self):
        params = _params(
            resources=[
                {
                    "id": "Clerk",
                    "name": "Clerk",
                    "cost_per_hour": "10",
                    "calendar": "cal",
                }
            ]
        )
        cost = event_costs(
            _log([("Clerk", "2025-01-06 10:00:00", "2025-01-06 12:00:00")]), params
        )["cost"].tolist()
        assert cost == [20.0]

    def test_bot_resource_name_differs_from_id(self):
        # The log carries the NAME; the join must fall back through name.
        params = _params(
            resources=[
                {
                    "id": "node_x_bot_resource",
                    "name": "Approve bot",
                    "cost_per_hour": 0,
                    "calendar": "cal",
                }
            ]
        )
        result = event_costs(
            _log([("Approve bot", "2025-01-06 10:00:00", "2025-01-06 12:00:00")]),
            params,
        )
        assert result["work_s"].tolist() == [7200.0]
        assert result["cost"].tolist() == [0.0]  # bot cost_per_hour 0

    def test_pooled_instance_suffix_resolves_to_base(self):
        # A pool with amount>1 logs its members as "<base>_0", "<base>_1"; params
        # names only the base. Both instances resolve to the base's rate/calendar.
        params = _params(
            resources=[
                {
                    "id": "botpool",
                    "name": "Bot pool",
                    "cost_per_hour": 5,
                    "calendar": "cal",
                }
            ]
        )
        result = event_costs(
            _log(
                [
                    ("Bot pool_0", "2025-01-06 10:00:00", "2025-01-06 11:00:00"),
                    ("Bot pool_1", "2025-01-06 10:00:00", "2025-01-06 12:00:00"),
                ]
            ),
            params,
        )
        assert result["work_s"].tolist() == [3600.0, 7200.0]
        assert result["cost"].tolist() == [5.0, 10.0]  # 1 h and 2 h at $5/hr

    def test_unknown_resource_with_work_raises(self):
        with pytest.raises(ValueError, match="no cost calendar"):
            event_costs(
                _log([("Ghost", "2025-01-06 10:00:00", "2025-01-06 12:00:00")]),
                _params(),
            )

    def test_unknown_resource_zero_duration_passes(self):
        result = event_costs(
            _log([("Ghost", "2025-01-06 10:00:00", "2025-01-06 10:00:00")]), _params()
        )
        assert result["cost"].tolist() == [0.0]

    def test_ambiguous_name_raises(self):
        params = _params(
            calendar_periods=NINE_TO_FIVE,
            resources=[
                {"id": "r1", "name": "Dup", "cost_per_hour": 10, "calendar": "cal"},
                {"id": "r2", "name": "Dup", "cost_per_hour": 20, "calendar": "cal"},
            ],
        )
        with pytest.raises(ValueError, match="conflicting"):
            event_costs(
                _log([("Dup", "2025-01-06 10:00:00", "2025-01-06 11:00:00")]), params
            )

    def test_empty_log(self):
        result = event_costs(_log([]), _params())
        assert result.empty
        assert list(result.columns) == ["work_s", "cost"]


class TestArrivalCalendar:
    def test_arrival_calendar_parsed(self):
        cal = calendars.arrival_calendar(_params())
        assert cal.is_working_time(_ts("2025-01-06 10:00:00"))
        assert not cal.is_working_time(_ts("2025-01-06 18:00:00"))
