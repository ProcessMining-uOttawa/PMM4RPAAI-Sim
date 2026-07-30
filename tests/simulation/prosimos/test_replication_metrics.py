"""Tests for core/simulation/prosimos/replication_metrics.py — no external tools required."""

from __future__ import annotations
import csv
import dataclasses
import json
from pathlib import Path

import pandas as pd
import pytest

from core.simulation.prosimos.replication_metrics import (
    _parse_section,
    _rework_metrics,
    _bot_failure_count,
    cycle_stats,
    observed_log_stats,
    task_totals,
    overall_kpis,
    replication_metrics,
    ReplicationMetrics,
    NO_RESOURCE,
    PROSIMOS_SECTION_TASK_STATS,
    PROSIMOS_COL_TOTAL_COST,
    PROSIMOS_COL_TOTAL_PROCESSING,
    PROSIMOS_SECTION_OVERALL,
    PROSIMOS_COL_ACCUMULATED,
    PROSIMOS_COL_TRACE_COUNT,
)
from core.constants import (
    COL_TOTAL_CYCLE_S,
    COL_TOTAL_REWORK_COUNT,
    COL_REWORK_RATE,
    COL_MEAN_REWORK_COUNT,
)
from core.metrics import MetricRegistry

# ── Helpers ───────────────────────────────────────────────────────────────────

BOT = "Auto Fix Bug"
ORIG = "Fix Bug"
FIXTURES = Path(__file__).parent.parent / "fixtures"
_ALLDAY = [
    {"from": "MONDAY", "to": "SUNDAY", "beginTime": "00:00:00", "endTime": "24:00:00"}
]
_NINE_TO_FIVE = [
    {"from": "MONDAY", "to": "FRIDAY", "beginTime": "09:00:00", "endTime": "17:00:00"}
]

_LOG_COLUMNS = [
    "case_id",
    "activity",
    "enable_time",
    "start_time",
    "end_time",
    "resource",
]


def _write_log(path: Path, rows: list[tuple]) -> Path:
    """rows: (case_id, activity, enable, start, end, resource)."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(_LOG_COLUMNS)
        for row in rows:
            w.writerow(row)
    return path


def _write_params(path: Path, calendar=_ALLDAY, rate: float = 10.0) -> Path:
    """One resource 'R' at the given rate on the given calendar (name == id)."""
    params = {
        "resource_calendars": [{"id": "cal", "time_periods": calendar}],
        "resource_profiles": [
            {
                "resource_list": [
                    {"id": "R", "name": "R", "cost_per_hour": rate, "calendar": "cal"}
                ]
            }
        ],
    }
    path.write_text(json.dumps(params))
    return path


def _metrics(
    tmp_path: Path, rows: list[tuple], calendar=_ALLDAY, **kwargs
) -> ReplicationMetrics:
    log = _write_log(tmp_path / "log.csv", rows)
    params = _write_params(tmp_path / "params.json", calendar)
    return replication_metrics(log, params, **kwargs)


def _row(case, start, end, activity="T", enable=None, resource="R") -> tuple:
    return (case, activity, enable or start, start, end, resource)


def _write_task_stats(path: Path, tasks: list[tuple]) -> Path:
    """tasks: (name, total_cost, total_processing_s)."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([PROSIMOS_SECTION_TASK_STATS])
        w.writerow(["Name", PROSIMOS_COL_TOTAL_COST, PROSIMOS_COL_TOTAL_PROCESSING])
        for name, cost, processing in tasks:
            w.writerow([name, str(cost), str(processing)])
        w.writerow([])
    return path


def _write_overall(path: Path, kpis: list[tuple], mode: str = "w") -> Path:
    """kpis: (name, min, max, average, accumulated, count). mode 'a' appends."""
    with open(path, mode, newline="") as f:
        w = csv.writer(f)
        w.writerow([PROSIMOS_SECTION_OVERALL])
        w.writerow(
            [
                "KPI",
                "Min",
                "Max",
                "Average",
                PROSIMOS_COL_ACCUMULATED,
                PROSIMOS_COL_TRACE_COUNT,
            ]
        )
        for row in kpis:
            w.writerow([str(cell) for cell in row])
        w.writerow([])
    return path


# ── _parse_section ────────────────────────────────────────────────────────────


class TestParseSection:
    def test_section_found(self):
        rows = [
            [PROSIMOS_SECTION_TASK_STATS],
            ["Name", PROSIMOS_COL_TOTAL_COST, "other"],
            ["task_a", "100.0", "x"],
            ["task_b", "50.0", "y"],
            [],
        ]
        hdrs, data = _parse_section(rows, PROSIMOS_SECTION_TASK_STATS)
        assert hdrs == ["Name", PROSIMOS_COL_TOTAL_COST, "other"]
        assert len(data) == 2
        assert data[0][1] == "100.0"

    def test_section_not_found(self):
        rows = [["Other Section"], ["col"], ["val"]]
        hdrs, data = _parse_section(rows, "Missing")
        assert hdrs == [] and data == []

    def test_terminates_at_blank_row(self):
        rows = [["My Section"], ["col"], ["row1"], [], ["row2"]]
        _, data = _parse_section(rows, "My Section")
        assert len(data) == 1

    def test_section_at_end_of_file(self):
        rows = [["My Section"]]
        hdrs, data = _parse_section(rows, "My Section")
        assert hdrs == [] and data == []


# ── task_totals / overall_kpis (checker oracle accessors) ─────────────────────


class TestTaskTotals:
    def test_returns_cost_and_processing(self, tmp_path):
        stats = _write_task_stats(
            tmp_path / "s.csv", [("A", 100.0, 3600.0), ("B", 50.0, 1800.0)]
        )
        result = task_totals(stats)
        assert result["A"] == {"cost": 100.0, "processing_s": 3600.0}
        assert result["B"] == {"cost": 50.0, "processing_s": 1800.0}

    def test_missing_task_section_raises(self, tmp_path):
        stats = _write_overall(tmp_path / "s.csv", [("cycle_time", 0, 0, 0, 1.0, 1)])
        with pytest.raises(ValueError, match="Individual Task Statistics"):
            task_totals(stats)

    def test_missing_cost_column_raises(self, tmp_path):
        stats = tmp_path / "s.csv"
        with open(stats, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([PROSIMOS_SECTION_TASK_STATS])
            w.writerow(["Name", "Some Other Column", PROSIMOS_COL_TOTAL_PROCESSING])
            w.writerow(["A", "50.0", "10.0"])
            w.writerow([])
        with pytest.raises(ValueError, match="Total Cost"):
            task_totals(stats)

    def test_missing_processing_column_raises(self, tmp_path):
        stats = tmp_path / "s.csv"
        with open(stats, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([PROSIMOS_SECTION_TASK_STATS])
            w.writerow(["Name", PROSIMOS_COL_TOTAL_COST])
            w.writerow(["A", "50.0"])
            w.writerow([])
        with pytest.raises(ValueError, match="Total Processing Time"):
            task_totals(stats)

    def test_non_numeric_raises(self, tmp_path):
        stats = _write_task_stats(tmp_path / "s.csv", [("A", "oops", 10.0)])
        with pytest.raises(ValueError, match="Non-numeric Total Cost"):
            task_totals(stats)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            task_totals(tmp_path / "nope.csv")


class TestOverallKpis:
    def test_returns_kpis(self, tmp_path):
        stats = _write_overall(
            tmp_path / "s.csv",
            [("cycle_time", 1.0, 9.0, 5.0, 500.0, 100)],
        )
        result = overall_kpis(stats)["cycle_time"]
        assert result == {
            "min": 1.0,
            "max": 9.0,
            "average": 5.0,
            "accumulated": 500.0,
            "count": 100.0,
        }

    def test_missing_overall_section_raises(self, tmp_path):
        stats = _write_task_stats(tmp_path / "s.csv", [("A", 1.0, 1.0)])
        with pytest.raises(ValueError, match="Overall Scenario Statistics"):
            overall_kpis(stats)

    def test_missing_accumulated_column_raises(self, tmp_path):
        stats = tmp_path / "s.csv"
        with open(stats, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([PROSIMOS_SECTION_OVERALL])
            w.writerow(["KPI", "Min", "Max", "Average", PROSIMOS_COL_TRACE_COUNT])
            w.writerow(["cycle_time", "0", "0", "0", "100"])
            w.writerow([])
        with pytest.raises(ValueError, match="Accumulated Value"):
            overall_kpis(stats)

    def test_missing_trace_count_column_raises(self, tmp_path):
        stats = tmp_path / "s.csv"
        with open(stats, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([PROSIMOS_SECTION_OVERALL])
            w.writerow(["KPI", "Min", "Max", "Average", PROSIMOS_COL_ACCUMULATED])
            w.writerow(["cycle_time", "0", "0", "0", "1.0"])
            w.writerow([])
        with pytest.raises(ValueError, match="Trace Ocurrences"):
            overall_kpis(stats)


# ── replication_metrics ───────────────────────────────────────────────────────


class TestReplicationMetrics:
    def test_returns_replication_metrics(self, tmp_path):
        m = _metrics(
            tmp_path, [_row("c1", "2025-01-06T08:00:00", "2025-01-06T10:00:00")]
        )
        assert isinstance(m, ReplicationMetrics)

    def test_cycle_time_mean(self, tmp_path):
        m = _metrics(
            tmp_path,
            [
                _row("c1", "2025-01-06T08:00:00", "2025-01-06T10:00:00"),  # 2 h
                _row("c2", "2025-01-06T08:00:00", "2025-01-06T12:00:00"),  # 4 h
            ],
        )
        assert m.mean_cycle_h == pytest.approx(3.0)

    def test_cycle_time_median_and_order_stats(self, tmp_path):
        m = _metrics(
            tmp_path,
            [
                _row("c1", "2025-01-06T08:00:00", "2025-01-06T10:00:00"),  # 2 h
                _row("c2", "2025-01-06T08:00:00", "2025-01-06T10:00:00"),  # 2 h
                _row("c3", "2025-01-06T08:00:00", "2025-01-06T16:00:00"),  # 8 h
            ],
        )
        # Asymmetric [2, 2, 8]: the tail pulls the mean to 4.0 while median stays 2.0.
        assert m.mean_cycle_h == pytest.approx(4.0)
        assert m.median_cycle_h == pytest.approx(2.0)
        assert m.min_cycle_h == pytest.approx(2.0)
        assert m.max_cycle_h == pytest.approx(8.0)

    def test_cycle_time_groups_by_case(self, tmp_path):
        # c1 has two events with a 30-min gap; its span includes the gap.
        m = _metrics(
            tmp_path,
            [
                _row("c1", "2025-01-06T08:00:00", "2025-01-06T09:00:00"),
                _row("c1", "2025-01-06T09:30:00", "2025-01-06T10:00:00"),
                _row("c2", "2025-01-06T08:00:00", "2025-01-06T09:00:00"),
            ],
        )
        # per-case spans: c1 = 2 h, c2 = 1 h → mean 1.5 h (a per-event mutant → 0.833).
        assert m.mean_cycle_h == pytest.approx(1.5)

    def test_mean_cost_is_mean_of_per_case_series(self, tmp_path):
        # rate 10/hr, 24/7 calendar. c1 has 2 one-hour events ($20), c2 & c3 one each
        # ($10). Per-case series [20, 10, 10] → mean 13.333, total 40. Discriminates
        # a per-event mean (40/4 = 10) and a per-case count.
        m = _metrics(
            tmp_path,
            [
                _row("c1", "2025-01-06T08:00:00", "2025-01-06T09:00:00"),
                _row("c1", "2025-01-06T09:00:00", "2025-01-06T10:00:00"),
                _row("c2", "2025-01-06T08:00:00", "2025-01-06T09:00:00"),
                _row("c3", "2025-01-06T08:00:00", "2025-01-06T09:00:00"),
            ],
        )
        assert m.mean_cost == pytest.approx(40.0 / 3)
        assert m.total_cost == pytest.approx(40.0)

    def test_cost_is_calendar_aware(self, tmp_path):
        # 9-5 calendar: a Mon 16:00 → Tue 10:00 task is 18 h wall but 2 h working
        # (Mon 16-17 + Tue 9-10) → cost 2 h × $10 = $20, not 18 × $10.
        m = _metrics(
            tmp_path,
            [_row("c1", "2025-01-06T16:00:00", "2025-01-07T10:00:00")],
            calendar=_NINE_TO_FIVE,
        )
        assert m.total_cost == pytest.approx(20.0)

    def test_total_cycle_s_ignores_enable_time(self, tmp_path):
        # enable_time 07:00 is present in the log but no clock reads it: both
        # total_cycle_s and mean_cycle_h anchor on the first task START (08:00).
        m = _metrics(
            tmp_path,
            [
                _row(
                    "c1",
                    "2025-01-06T08:00:00",
                    "2025-01-06T10:00:00",
                    enable="2025-01-06T07:00:00",
                )
            ],
        )
        assert m.total_cycle_s == pytest.approx(2 * 3600.0)
        assert m.mean_cycle_h == pytest.approx(2.0)

    def test_total_cycle_s_equals_mean_times_n(self, tmp_path):
        # total and mean share one anchor pair, so total = mean × n × 3600 holds
        # by construction (the identity demo mode also relies on).
        m = _metrics(
            tmp_path,
            [
                _row("c1", "2025-01-06T08:00:00", "2025-01-06T10:00:00"),  # 2 h
                _row("c2", "2025-01-06T08:00:00", "2025-01-06T12:00:00"),  # 4 h
            ],
        )
        assert m.total_cycle_s == pytest.approx(m.mean_cycle_h * 2 * 3600.0)
        assert m.total_cycle_s == pytest.approx(6 * 3600.0)

    def test_flag_on_log_raises(self, tmp_path):
        # An intermediate-event row marks a --is_event_added_to_log run; parsing
        # it would corrupt rework/cycle, so the reader rejects the log, naming
        # the flag.
        with pytest.raises(ValueError, match="is_event_added_to_log"):
            _metrics(
                tmp_path,
                [
                    (
                        "c1",
                        "Event_x",
                        "2025-01-06T07:00:00",
                        "2025-01-06T07:00:00",
                        "2025-01-06T08:00:00",
                        NO_RESOURCE,
                    ),
                    _row("c1", "2025-01-06T08:00:00", "2025-01-06T10:00:00"),
                ],
            )

    def test_bot_failure_count_field(self, tmp_path):
        m = _metrics(
            tmp_path,
            [
                _row("c1", "2025-01-06T08:00:00", "2025-01-06T09:00:00", activity=BOT),
                _row("c1", "2025-01-06T09:00:00", "2025-01-06T10:00:00", activity=ORIG),
                _row("c2", "2025-01-06T08:00:00", "2025-01-06T09:00:00", activity=BOT),
            ],
            bot_task_name=BOT,
            original_task_name=ORIG,
        )
        assert m.total_bot_failure_count == 1.0
        assert m.total_rework_count == 0.0  # the failure pair is not rework

    def test_missing_params_file_raises(self, tmp_path):
        log = _write_log(
            tmp_path / "log.csv",
            [_row("c1", "2025-01-06T08:00:00", "2025-01-06T09:00:00")],
        )
        with pytest.raises(FileNotFoundError):
            replication_metrics(log, tmp_path / "nonexistent.json")

    def test_malformed_params_raises(self, tmp_path):
        log = _write_log(
            tmp_path / "log.csv",
            [_row("c1", "2025-01-06T08:00:00", "2025-01-06T09:00:00")],
        )
        params = tmp_path / "params.json"
        params.write_text("{ not valid json")
        with pytest.raises(ValueError):
            replication_metrics(log, params)


# ── cycle_stats / observed_log_stats (the fidelity kernel) ────────────────────


def _activity_df(rows: list[tuple[str, str, str]]) -> pd.DataFrame:
    """rows: (case_id, start_iso, end_iso) — the columns cycle_stats reads."""
    return pd.DataFrame(
        {
            "case_id": [case for case, _, _ in rows],
            "activity": ["T"] * len(rows),
            "start_time": pd.to_datetime([start for _, start, _ in rows]),
            "end_time": pd.to_datetime([end for _, _, end in rows]),
        }
    )


class TestCycleStats:
    def test_hand_computed_spans(self):
        # Asymmetric spans so mean (6.0) != median (4.0) — a two-case fixture
        # would make them definitionally equal and let a mixup pass.
        stats = cycle_stats(
            _activity_df(
                [
                    ("c1", "2025-01-06T08:00:00", "2025-01-06T10:00:00"),  # 2 h
                    ("c2", "2025-01-06T08:00:00", "2025-01-06T12:00:00"),  # 4 h
                    ("c3", "2025-01-06T08:00:00", "2025-01-06T20:00:00"),  # 12 h
                ]
            )
        )
        assert stats.mean_cycle_h == pytest.approx(6.0)
        assert stats.median_cycle_h == pytest.approx(4.0)
        assert stats.min_cycle_h == pytest.approx(2.0)
        assert stats.max_cycle_h == pytest.approx(12.0)
        assert stats.n_cases == 3

    def test_total_cycle_s_equals_mean_times_n(self):
        stats = cycle_stats(
            _activity_df(
                [
                    ("c1", "2025-01-06T08:00:00", "2025-01-06T10:00:00"),  # 2 h
                    ("c2", "2025-01-06T08:00:00", "2025-01-06T12:00:00"),  # 4 h
                ]
            )
        )
        assert stats.total_cycle_s == pytest.approx(6 * 3600)
        assert stats.total_cycle_s == pytest.approx(
            stats.mean_cycle_h * stats.n_cases * 3600
        )

    def test_case_span_includes_mid_case_gaps(self):
        # Two rows with a 30-min gap: the span is wall-clock first-start →
        # last-end, not a sum of task durations.
        stats = cycle_stats(
            _activity_df(
                [
                    ("c1", "2025-01-06T08:00:00", "2025-01-06T09:00:00"),
                    ("c1", "2025-01-06T09:30:00", "2025-01-06T10:00:00"),
                ]
            )
        )
        assert stats.mean_cycle_h == pytest.approx(2.0)
        assert stats.n_cases == 1


class TestObservedLogStats:
    """The coherence pins: both sides of the fidelity comparison must agree on
    identical input — the invariant the comparison rests on."""

    GOLDEN = FIXTURES / "golden_fix"

    def test_cycle_fields_equal_replication_metrics(self):
        m = replication_metrics(self.GOLDEN / "log.csv", self.GOLDEN / "params.json")
        observed = observed_log_stats(self.GOLDEN / "log.csv")
        # Exact ==, not approx: same kernel, same code path.
        assert observed.mean_cycle_h == m.mean_cycle_h
        assert observed.median_cycle_h == m.median_cycle_h
        assert observed.min_cycle_h == m.min_cycle_h
        assert observed.max_cycle_h == m.max_cycle_h
        assert observed.total_cycle_s == m.total_cycle_s
        assert observed.rework_rate == m.rework_rate

    def test_n_cases_counts_the_golden_run(self):
        assert observed_log_stats(self.GOLDEN / "log.csv").n_cases == 60

    def test_flag_on_log_raises(self, tmp_path):
        log = _write_log(
            tmp_path / "log.csv",
            [
                (
                    "c1",
                    "Event_x",
                    "2025-01-06T07:00:00",
                    "2025-01-06T07:00:00",
                    "2025-01-06T07:00:00",
                    NO_RESOURCE,
                ),
                _row("c1", "2025-01-06T08:00:00", "2025-01-06T10:00:00"),
            ],
        )
        with pytest.raises(ValueError, match="is_event_added_to_log"):
            observed_log_stats(log)

    def test_mixed_utc_offsets_parse_offset_aware(self, tmp_path):
        # A real uploaded log spanning a daylight-saving switch carries two UTC
        # offsets in one column — which pandas' parse_dates silently leaves as
        # strings, so the reader must normalize to UTC itself. The span is
        # offset-aware by construction: first start 01:00+01:00 (= 00:00Z) to
        # last end 04:00+02:00 (= 02:00Z) is 2 h — an offset-stripping parse
        # would read 3 h.
        log = _write_log(
            tmp_path / "log.csv",
            [
                (
                    "c1",
                    "A",
                    "2025-03-30T01:00:00+01:00",
                    "2025-03-30T01:00:00+01:00",
                    "2025-03-30T01:30:00+01:00",
                    "R",
                ),
                (
                    "c1",
                    "B",
                    "2025-03-30T03:00:00+02:00",
                    "2025-03-30T03:00:00+02:00",
                    "2025-03-30T04:00:00+02:00",
                    "R",
                ),
            ],
        )
        observed = observed_log_stats(log)
        assert observed.n_cases == 1
        assert observed.mean_cycle_h == pytest.approx(2.0)

    def test_asdict_keys_cover_the_comparison_columns(self):
        # fidelity_table reads the asdict record by COL_* key, and derives its
        # cycle rows from the registry — so derive the expected set from the
        # registry too: a new CYCLE_TIME indicator must fail HERE, naming
        # ObservedStats as the file needing the field, not as an incidental
        # KeyError inside a fixture.
        keys = set(dataclasses.asdict(observed_log_stats(self.GOLDEN / "log.csv")))
        comparison_columns = {
            indicator.results_column
            for indicator in MetricRegistry.CYCLE_TIME.indicators
        } | {
            COL_TOTAL_CYCLE_S,
            MetricRegistry.REWORK_RATE.default_indicator.results_column,
        }
        assert comparison_columns <= keys


# ── _rework_metrics ───────────────────────────────────────────────────────────


def _df(*rows: tuple[str, str]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["case_id", "activity"])


class TestReworkMetrics:
    def test_no_rework_count_zero(self):
        assert (
            _rework_metrics(_df(("C1", ORIG), ("C2", ORIG)))[COL_TOTAL_REWORK_COUNT]
            == 0.0
        )

    def test_no_rework_rate_zero(self):
        assert _rework_metrics(_df(("C1", ORIG), ("C2", ORIG)))[COL_REWORK_RATE] == 0.0

    def test_standard_rework_count(self):
        df = _df(("C1", ORIG), ("C1", ORIG), ("C2", ORIG))
        assert _rework_metrics(df)[COL_TOTAL_REWORK_COUNT] == 1.0

    def test_standard_rework_rate(self):
        df = _df(("C1", ORIG), ("C1", ORIG), ("C2", ORIG))
        assert _rework_metrics(df)[COL_REWORK_RATE] == pytest.approx(50.0)

    def test_mean_rework_count(self):
        df = _df(("C1", ORIG), ("C1", ORIG), ("C2", ORIG))
        assert _rework_metrics(df)[COL_MEAN_REWORK_COUNT] == pytest.approx(0.5)

    def test_standard_rework_three_repeats(self):
        df = _df(("C1", ORIG), ("C1", ORIG), ("C1", ORIG))
        assert _rework_metrics(df)[COL_TOTAL_REWORK_COUNT] == 2.0

    def test_standard_rework_multiple_activities(self):
        df = _df(("C1", "A"), ("C1", "A"), ("C1", "B"), ("C1", "B"))
        assert _rework_metrics(df)[COL_TOTAL_REWORK_COUNT] == 2.0

    def test_bot_failure_pair_is_not_rework(self):
        df = _df(("C1", BOT), ("C1", ORIG), ("C2", BOT))
        r = _rework_metrics(df)
        assert r[COL_TOTAL_REWORK_COUNT] == 0.0
        assert r[COL_REWORK_RATE] == 0.0

    def test_repeated_activity_alongside_bot_pair(self):
        df = _df(("C1", BOT), ("C1", ORIG), ("C1", ORIG))
        r = _rework_metrics(df)
        assert r[COL_TOTAL_REWORK_COUNT] == 1.0
        assert r[COL_REWORK_RATE] == 100.0

    def test_rework_count_sums_across_cases(self):
        df = _df(("C1", ORIG), ("C1", ORIG), ("C2", BOT), ("C2", ORIG), ("C3", ORIG))
        r = _rework_metrics(df)
        assert r[COL_TOTAL_REWORK_COUNT] == 1.0
        assert r[COL_REWORK_RATE] == pytest.approx(100 / 3)

    def test_missing_activity_column_zero(self):
        r = _rework_metrics(pd.DataFrame({"case_id": ["C1"]}))
        assert r[COL_TOTAL_REWORK_COUNT] == 0.0
        assert r[COL_REWORK_RATE] == 0.0
        assert r[COL_MEAN_REWORK_COUNT] == 0.0


# ── _bot_failure_count ────────────────────────────────────────────────────────


class TestBotFailureCount:
    def test_failure_pair_counts_one(self):
        assert (
            _bot_failure_count(_df(("C1", BOT), ("C1", ORIG), ("C2", BOT)), BOT, ORIG)
            == 1.0
        )

    def test_bot_success_zero(self):
        assert _bot_failure_count(_df(("C1", BOT), ("C2", BOT)), BOT, ORIG) == 0.0

    def test_manual_only_zero(self):
        assert _bot_failure_count(_df(("C1", ORIG), ("C2", ORIG)), BOT, ORIG) == 0.0

    def test_binary_per_case(self):
        df = _df(("C1", BOT), ("C1", ORIG), ("C1", BOT), ("C1", ORIG))
        assert _bot_failure_count(df, BOT, ORIG) == 1.0

    def test_sums_across_cases(self):
        df = _df(("C1", BOT), ("C1", ORIG), ("C2", BOT), ("C2", ORIG), ("C3", BOT))
        assert _bot_failure_count(df, BOT, ORIG) == 2.0

    def test_unknown_task_names_zero(self):
        assert _bot_failure_count(_df(("C1", BOT), ("C1", ORIG)), None, None) == 0.0

    def test_missing_activity_column_zero(self):
        assert _bot_failure_count(pd.DataFrame({"case_id": ["C1"]}), BOT, ORIG) == 0.0
