"""Dimension 5 · A-share 估值 — locally computed from available data.

All metrics computed from baostock + financials data.
No eastmoney HTTP dependency (blocked by Clash TUN).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from backend.app.services.fetchers.utils import (
    normalize_code,
    safe_fetch,
    to_baostock_code,
    to_num,
)

logger = logging.getLogger(__name__)


def fetch_valuation(
    ticker: str,
    market_cap: float | None = None,
    latest_revenue: float | None = None,
    revenue_growth: float | None = None,
    net_profit_growth: float | None = None,
) -> dict[str, Any]:
    """Compute all valuation metrics locally.

    Args:
        ticker: stock code
        market_cap: 总市值（亿）, from snapshot
        latest_revenue: 最新年度营收（亿）, from financials
        revenue_growth: 营收增速(%), from financials
        net_profit_growth: 净利润增速(%), from financials (optional)
    """
    code = normalize_code(ticker)
    return safe_fetch(
        lambda: _compute(code, market_cap, latest_revenue, revenue_growth, net_profit_growth),
        default={},
    )


def _compute(
    code: str,
    market_cap: float | None,
    latest_revenue: float | None,
    revenue_growth: float | None,
    net_profit_growth: float | None,
) -> dict:
    out: dict[str, Any] = {}

    # ── 1. PE / PB + 5-year percentile from baostock ─────────────────────
    _fill_baostock(out, code)

    # ── 2. PS(TTM) = market_cap / revenue ────────────────────────────────
    pe_ttm = out.get("pe_ttm")
    if market_cap and latest_revenue and latest_revenue > 0:
        out["ps_ttm"] = round(market_cap / latest_revenue, 2)

    # ── 3. PEG = PE / growth_rate ────────────────────────────────────────
    growth = revenue_growth or net_profit_growth
    if pe_ttm and growth and growth > 0:
        out["peg"] = round(pe_ttm / growth, 2)
    elif pe_ttm and growth and growth <= 0:
        out["peg"] = None  # negative growth → PEG meaningless

    # ── 4. PE dynamic/static are same as TTM from baostock ────────────────
    if pe_ttm:
        out["pe_dynamic"] = pe_ttm
        out["pe_static"] = pe_ttm

    out["_status"] = "ok"
    return out


def _fill_baostock(out: dict, code: str) -> None:
    """PE, PB + 5-year historical percentile from baostock (TCP, stable)."""
    try:
        import baostock as bs

        bs_code = to_baostock_code(code)
        end = date.today().strftime("%Y-%m-%d")
        start_5y = (date.today() - timedelta(days=365 * 5)).strftime("%Y-%m-%d")

        lg = bs.login()
        if lg.error_code != "0":
            return

        rs = bs.query_history_k_data_plus(
            bs_code, "date,close,peTTM,pbMRQ",
            start_date=start_5y, end_date=end,
            frequency="d", adjustflag="3",
        )
        df = rs.get_data()
        bs.logout()

        if df.empty:
            return

        latest = df.iloc[-1]
        pe_raw = to_num(latest.get("peTTM"))
        pb_raw = to_num(latest.get("pbMRQ"))

        if pe_raw and pe_raw > 0:
            out["pe_ttm"] = pe_raw
        if pb_raw and pb_raw > 0:
            out["pb"] = pb_raw

        # 5-year PE percentile
        pe_series = df["peTTM"].apply(to_num).dropna()
        if pe_raw and pe_raw > 0 and len(pe_series) > 0:
            rank = (pe_series < pe_raw).sum()
            out["pe_historical_percentile"] = round(rank / len(pe_series) * 100, 1)
            out["pe_5y_min"] = round(float(pe_series.min()), 2)
            out["pe_5y_max"] = round(float(pe_series.max()), 2)
            out["pe_5y_median"] = round(float(pe_series.median()), 2)

        # 5-year PB percentile
        pb_series = df["pbMRQ"].apply(to_num).dropna()
        if pb_raw and pb_raw > 0 and len(pb_series) > 0:
            rank = (pb_series < pb_raw).sum()
            out["pb_historical_percentile"] = round(rank / len(pb_series) * 100, 1)
            out["pb_5y_min"] = round(float(pb_series.min()), 2)
            out["pb_5y_max"] = round(float(pb_series.max()), 2)
            out["pb_5y_median"] = round(float(pb_series.median()), 2)
    except Exception as exc:
        out["_baostock_error"] = str(exc)[:200]
