"""Tests for fetcher utility helpers (no network)."""

from __future__ import annotations

from backend.app.services.fetchers.utils import (
    normalize_code,
    pct_change,
    safe_div,
    safe_fetch,
    to_baostock_code,
    to_num,
    to_pct,
    to_yi,
)


def test_normalize_code_strips_suffix():
    assert normalize_code("600519.SH") == "600519"
    assert normalize_code("000001.SZ") == "000001"
    assert normalize_code(" 600519 ") == "600519"


def test_to_baostock_code_exchange():
    assert to_baostock_code("600519") == "sh.600519"
    assert to_baostock_code("000001") == "sz.000001"
    assert to_baostock_code("300750") == "sz.300750"


def test_to_num_and_pct():
    assert to_num("1,234.5") == 1234.5
    assert to_num("18.7%") == 18.7
    assert to_num(None) is None
    assert to_num("n/a") is None
    assert to_pct("18.7%") == 18.7


def test_to_yi():
    assert to_yi(100_000_000) == 1.0


def test_safe_div_and_pct_change():
    assert safe_div(10, 2) == 5.0
    assert safe_div(10, 0) is None
    assert pct_change(100, 110) == 10.0
    assert pct_change(0, 110) is None


def test_safe_fetch_returns_error_dict():
    def boom():
        raise ValueError("network down")

    out = safe_fetch(boom, default={})
    assert out["_status"] == "failed"
    assert "network down" in out["_error"]
