"""Dimension 3 · A-share 财报 — financial metrics from akshare.

Data sources:
  - stock_financial_analysis_indicator → 80+ ratios (ROE, margins, debt ratio, etc.)
  - stock_financial_abstract → revenue/profit history for growth calc
  - stock_dividend_cninfo → recent dividend data for yield calculation
"""

from __future__ import annotations

import logging
from typing import Any

from backend.app.services.fetchers.utils import (
    normalize_code,
    safe_fetch,
    to_num,
    to_pct,
    to_yi,
    try_ak,
)

logger = logging.getLogger(__name__)


def fetch_financials(ticker: str, current_price: float | None = None) -> dict[str, Any]:
    code = normalize_code(ticker)
    return safe_fetch(lambda: _fetch(code, current_price), default={})


def _fetch(code: str, current_price: float | None) -> dict:
    out: dict[str, Any] = {}
    import akshare as ak

    # ── 1. Financial abstract → revenue & profit history ──────────────────
    df_abs = try_ak(ak.stock_financial_abstract, symbol=code, timeout=15)
    if df_abs is not None:
        period_cols = [c for c in df_abs.columns if c not in ("选项", "指标")]
        annual_cols = sorted([c for c in period_cols if str(c).endswith("1231")])[-6:]

        def _row(keywords: list[str]) -> list:
            for kw in keywords:
                mask = df_abs["指标"].astype(str).str.contains(kw, na=False)
                if mask.any():
                    return [to_yi(df_abs[mask][c].iloc[0]) for c in annual_cols]
            return []

        out["revenue_history"] = _row(["营业总收入", "营业收入", "营业总收入(万元)"])
        out["net_profit_history"] = _row([
            "归属于母公司所有者的净利润", "净利润(不含少数股东损益)", "净利润",
        ])
        out["financial_years"] = [str(c)[:4] for c in annual_cols]

        rev = out.get("revenue_history", [])
        if len(rev) >= 2 and rev[-1] and rev[-2] and rev[-2] > 0:
            out["revenue_growth"] = round((rev[-1] / rev[-2] - 1) * 100, 2)

    # ── 2. Financial indicators → all ratios ─────────────────────────────
    df_ind = try_ak(ak.stock_financial_analysis_indicator, symbol=code, start_year="2020", timeout=15)
    if df_ind is not None:
        date_col = _find_date_col(df_ind)
        df_ind = df_ind.sort_values(date_col)
        df_annual = df_ind[df_ind[date_col].astype(str).str.endswith("12-31")]

        # --- Profitability ---
        out["roe_history"] = _extract_series(df_annual, ["净资产收益率(%)"])
        if out["roe_history"]:
            out["roe"] = out["roe_history"][-1]

        out["net_margin"] = _extract_latest(df_annual, ["销售净利率(%)", "营业净利率(%)"])

        # Gross margin: try direct column, fallback to 100 - cost_rate, then operating margin
        gm = _extract_latest_non_null(df_ind, ["销售毛利率(%)", "营业毛利率(%)"], date_col)
        if gm is None:
            cost_rate = _extract_latest(df_annual, ["主营业务成本率(%)", "营业成本率(%)"])
            if cost_rate is not None:
                gm = round(100 - cost_rate, 2)
        if gm is None:
            gm = _extract_latest(df_annual, ["营业利润率(%)"])
        out["gross_margin"] = gm

        # --- Financial health ---
        health: dict[str, Any] = {}
        health["debt_ratio"] = _extract_latest(df_annual, ["资产负债率(%)"])
        health["current_ratio"] = _extract_latest(df_annual, ["流动比率", "流动比率(倍)"])
        health["quick_ratio"] = _extract_latest(df_annual, ["速动比率", "速动比率(倍)"])
        # ROA: compute from net profit / total assets if column not available
        health["roa"] = _extract_latest(df_annual, [
            "总资产收益率(%)", "资产收益率(%)", "总资产报酬率(%)",
        ])
        # Fallback: compute ROA from net_profit / total_assets
        if health["roa"] is None:
            ta_col = _find_any_col(df_annual, ["总资产(元)", "资产总计(元)"])
            np_col = _find_any_col(df_annual, ["净利润(元)", "归属于母公司所有者的净利润(元)"])
            if ta_col and np_col:
                ta_val = to_num(df_annual[ta_col].iloc[-1])
                np_val = to_num(df_annual[np_col].iloc[-1])
                if ta_val and np_val and ta_val > 0:
                    health["roa"] = round(np_val / ta_val * 100, 2)

        # ROIC estimate
        roe_ann = _extract_latest(df_annual, ["净资产收益率(%)"])
        if roe_ann and health["debt_ratio"]:
            health["roic"] = round(roe_ann * (1 - health["debt_ratio"] / 100), 2)

        out["financial_health"] = health

    # ── 3. Dividend → yield ─────────────────────────────────────────────
    df_div = try_ak(ak.stock_dividend_cninfo, symbol=code, timeout=20)
    if df_div is not None:
        # Find column names (varies by akshare version)
        from backend.app.services.fetchers.utils import find_col
        div_col = find_col(df_div, ["派息比例", "每股派息", "dividend_per_share"])
        date_col_div = find_col(df_div, ["实施公告发布日期", "公告日期", "股权登记日", "date"])
        if div_col and date_col_div:
            df_div = df_div.sort_values(date_col_div)
            rows = df_div.tail(6)
            out["dividend_years"] = [
                str(r[date_col_div]).split("-")[0] if r[date_col_div] else ""
                for _, r in rows.iterrows()
            ]
            out["dividend_amounts"] = [
                to_num(r[div_col]) for _, r in rows.iterrows()
            ]
            # Dividend yield = (dividend_per_10 / 10) / current_price * 100
            latest_div = to_num(rows.iloc[-1][div_col])
            if latest_div and current_price and current_price > 0:
                # 派息比例 is usually 元/10股
                div_per_share = latest_div / 10 if latest_div > 10 else latest_div
                yield_pct = round(div_per_share / current_price * 100, 2)
                out["dividend_yields"] = [yield_pct]

    out.setdefault("roe_history", [])
    out.setdefault("revenue_history", [])
    out.setdefault("net_profit_history", [])
    out.setdefault("financial_years", [])
    out.setdefault("financial_health", {})
    out.setdefault("dividend_years", [])
    out.setdefault("dividend_amounts", [])
    out.setdefault("dividend_yields", [])
    out["_status"] = "ok"
    return out


# ── helpers ──────────────────────────────────────────────────────────────────

def _find_date_col(df) -> str:
    for c in ["日期", "报告期", "截止日期"]:
        if c in df.columns:
            return c
    return df.columns[0]


def _extract_latest(df, candidates: list[str]) -> float | None:
    """Extract the latest annual value for any matching column."""
    for col in candidates:
        if col in df.columns:
            vals = [to_pct(v) for v in df[col].tail(3)]
            if vals and any(v is not None for v in vals):
                return vals[-1]
    return None


def _extract_latest_non_null(df, candidates: list[str], date_col: str) -> float | None:
    """Search ALL rows (not just annual) for the last non-null value."""
    for col in candidates:
        if col in df.columns:
            series = df[col].dropna()
            if not series.empty:
                return to_pct(series.iloc[-1])
    return None


def _extract_series(df, candidates: list[str]) -> list[float | None]:
    """Extract tail series for any matching column."""
    for col in candidates:
        if col in df.columns:
            return [to_pct(v) for v in df[col].tail(6)]
    return []


def _find_any_col(df, candidates: list[str]) -> str | None:
    """Return the first matching column name, or None."""
    for col in candidates:
        if col in df.columns:
            return col
    return None
