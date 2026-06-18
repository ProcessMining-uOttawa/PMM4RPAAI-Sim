"""Tests for rework metric computation in core/simulation/prosimos_csv.py."""

from __future__ import annotations

import pandas as pd
import pytest

from core.simulation.prosimos_csv import _rework_metrics
from core.constants import COL_TOTAL_REWORK_COUNT, COL_REWORK_RATE

BOT = "Auto Fix Bug"
ORIG = "Fix Bug"


def _df(*rows: tuple[str, str]) -> pd.DataFrame:
    """Build a minimal event-log DataFrame with only case_id and activity columns."""
    return pd.DataFrame(rows, columns=["case_id", "activity"])


class TestReworkMetrics:
    # ── no rework ─────────────────────────────────────────────────────────────

    def test_no_rework_count_zero(self):
        df = _df(("C1", ORIG), ("C2", ORIG))
        r = _rework_metrics(df)
        assert r[COL_TOTAL_REWORK_COUNT] == 0.0

    def test_no_rework_rate_zero(self):
        df = _df(("C1", ORIG), ("C2", ORIG))
        r = _rework_metrics(df)
        assert r[COL_REWORK_RATE] == 0.0

    # ── standard rework (same activity twice in one case) ─────────────────────

    def test_standard_rework_count(self):
        df = _df(("C1", ORIG), ("C1", ORIG), ("C2", ORIG))
        r = _rework_metrics(df)
        assert r[COL_TOTAL_REWORK_COUNT] == 1.0

    def test_standard_rework_rate(self):
        # 1 of 2 cases has rework
        df = _df(("C1", ORIG), ("C1", ORIG), ("C2", ORIG))
        r = _rework_metrics(df)
        assert r[COL_REWORK_RATE] == pytest.approx(50.0)

    def test_standard_rework_three_repeats(self):
        # activity appears 3 times → 2 extra occurrences
        df = _df(("C1", ORIG), ("C1", ORIG), ("C1", ORIG))
        r = _rework_metrics(df)
        assert r[COL_TOTAL_REWORK_COUNT] == 2.0

    def test_standard_rework_multiple_activities(self):
        # two different activities each repeated once → 2 extra
        df = _df(("C1", "A"), ("C1", "A"), ("C1", "B"), ("C1", "B"))
        r = _rework_metrics(df)
        assert r[COL_TOTAL_REWORK_COUNT] == 2.0

    # ── bot-failure rework ────────────────────────────────────────────────────

    def test_bot_failure_adds_one(self):
        # bot ran and failed; human picked up — neither activity repeated
        df = _df(("C1", BOT), ("C1", ORIG), ("C2", BOT))
        r = _rework_metrics(df, bot_task_name=BOT, original_task_name=ORIG)
        assert r[COL_TOTAL_REWORK_COUNT] == 1.0

    def test_bot_failure_rate(self):
        df = _df(("C1", BOT), ("C1", ORIG), ("C2", BOT))
        r = _rework_metrics(df, bot_task_name=BOT, original_task_name=ORIG)
        assert r[COL_REWORK_RATE] == pytest.approx(50.0)  # 1 of 2 cases

    def test_bot_success_no_rework(self):
        # bot succeeded; original task never ran
        df = _df(("C1", BOT), ("C2", BOT))
        r = _rework_metrics(df, bot_task_name=BOT, original_task_name=ORIG)
        assert r[COL_TOTAL_REWORK_COUNT] == 0.0
        assert r[COL_REWORK_RATE] == 0.0

    def test_manual_path_no_bot_failure_rework(self):
        # manual path: original task ran, bot task never ran → no bot-failure rework
        df = _df(("C1", ORIG), ("C2", ORIG))
        r = _rework_metrics(df, bot_task_name=BOT, original_task_name=ORIG)
        assert r[COL_TOTAL_REWORK_COUNT] == 0.0

    # ── combined standard + bot-failure ───────────────────────────────────────

    def test_combined_rework_count(self):
        # C1: bot failed (+1) AND human task ran twice (+1) → 2
        df = _df(("C1", BOT), ("C1", ORIG), ("C1", ORIG))
        r = _rework_metrics(df, bot_task_name=BOT, original_task_name=ORIG)
        assert r[COL_TOTAL_REWORK_COUNT] == 2.0

    def test_combined_rate_all_cases(self):
        df = _df(("C1", BOT), ("C1", ORIG), ("C1", ORIG))
        r = _rework_metrics(df, bot_task_name=BOT, original_task_name=ORIG)
        assert r[COL_REWORK_RATE] == 100.0

    # ── bot params ignored when not provided ─────────────────────────────────

    def test_bot_failure_ignored_without_params(self):
        # same data as bot_failure_adds_one but no params → only standard rework
        df = _df(("C1", BOT), ("C1", ORIG), ("C2", BOT))
        r = _rework_metrics(df)
        assert r[COL_TOTAL_REWORK_COUNT] == 0.0
        assert r[COL_REWORK_RATE] == 0.0

    # ── multi-case summary ────────────────────────────────────────────────────

    def test_rework_count_sums_across_cases(self):
        # C1: ORIG twice (+1), C2: bot failure (+1), C3: clean
        df = _df(
            ("C1", ORIG),
            ("C1", ORIG),
            ("C2", BOT),
            ("C2", ORIG),
            ("C3", ORIG),
        )
        r = _rework_metrics(df, bot_task_name=BOT, original_task_name=ORIG)
        assert r[COL_TOTAL_REWORK_COUNT] == 2.0
        assert r[COL_REWORK_RATE] == pytest.approx(200 / 3)
