"""Benchmark tests for context compaction token savings."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.benchmark_context_compaction import (  # noqa: E402
    build_scenario_first_analysis_plus_followups,
    build_scenario_uniform_rounds,
    run_benchmark,
)
from backend.app.services.agent import MAX_TOOL_ROUNDS_KEPT  # noqa: E402


def test_no_compaction_under_threshold():
    r = run_benchmark("5轮", build_scenario_uniform_rounds(5))
    assert r.compacted is False
    assert r.overall_saved_pct == 0.0


def test_compaction_saves_significant_tokens_on_heavy_session():
    r = run_benchmark("首诊+3追问", build_scenario_first_analysis_plus_followups(3))
    assert r.compacted is True
    assert r.tool_rounds > MAX_TOOL_ROUNDS_KEPT
    # full context should shrink meaningfully
    assert r.overall_saved_pct >= 15.0
    # compressed old section should shrink heavily
    assert r.old_section_saved_pct >= 85.0


def test_compaction_old_section_near_90_percent_plus():
    r = run_benchmark("10轮", build_scenario_uniform_rounds(10))
    assert r.compacted is True
    assert r.old_section_saved_pct >= 90.0


@pytest.mark.parametrize("rounds,expect_compact", [
    (5, False),
    (6, True),
    (8, True),
])
def test_compaction_trigger_threshold(rounds, expect_compact):
    r = run_benchmark(f"{rounds}轮", build_scenario_uniform_rounds(rounds))
    assert r.compacted is expect_compact
