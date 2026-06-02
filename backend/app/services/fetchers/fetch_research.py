"""Dimension 16 · A-share 研报汇总 — 券商评级 + 盈利预测."""

from __future__ import annotations

import logging
from typing import Any

from backend.app.services.fetchers.utils import normalize_code, safe_fetch, to_num, try_ak

logger = logging.getLogger(__name__)

RATINGS_CN = {"买入": "buy", "增持": "overweight", "中性": "hold", "减持": "underweight", "卖出": "sell"}


def fetch_research(ticker: str) -> dict[str, Any]:
    code = normalize_code(ticker)
    return safe_fetch(lambda: _fetch(code), default={})


def _fetch(code: str) -> dict:
    out: dict[str, Any] = {}
    import akshare as ak

    # ── 研报列表 ──────────────────────────────────────────────────────────
    # stock_research_report_em returns 16 columns, fixed positions:
    #   [0]=序号 [1]=股票代码 [2]=股票简称 [3]=研报标题
    #   [4]=评级 [5]=研究机构 [6]=分析师 [13]=行业 [14]=日期
    #   [7-12]=2026/27/28 EPS和PE预测
    df = try_ak(ak.stock_research_report_em, symbol=code)
    reports = []
    if df is not None and not df.empty:
        for _, r in df.head(20).iterrows():
            raw_rating = str(r.iloc[4]) if len(r) > 4 else ""
            reports.append({
                "date": str(r.iloc[14])[:10] if len(r) > 14 else "",
                "institution": str(r.iloc[5]) if len(r) > 5 else "",
                "analyst": str(r.iloc[6]) if len(r) > 6 else "",
                "rating": RATINGS_CN.get(raw_rating, raw_rating),
                "rating_raw": raw_rating,
                "title": str(r.iloc[3])[:100] if len(r) > 3 else "",
                # Extract EPS forecasts from cols 7/9/11
                "eps_2026": to_num(r.iloc[7]) if len(r) > 7 else None,
                "eps_2027": to_num(r.iloc[9]) if len(r) > 9 else None,
                "eps_2028": to_num(r.iloc[11]) if len(r) > 11 else None,
            })
    out["reports"] = reports

    # ── 评级统计 ──────────────────────────────────────────────────────────
    summary = {"buy": 0, "overweight": 0, "hold": 0, "underweight": 0, "sell": 0, "total": len(reports)}
    for r in reports:
        if r["rating"] in summary:
            summary[r["rating"]] += 1

    if reports and summary["total"] > 0:
        buy_pct = summary["buy"] / summary["total"]
        summary["consensus"] = (
            "强烈看多" if buy_pct >= 0.7
            else "看多" if buy_pct >= 0.5
            else "中性" if summary["hold"] >= summary["buy"]
            else "分歧较大"
        )
    else:
        summary["consensus"] = "无数据"

    out["rating_summary"] = summary

    # ── 盈利预测 (同花顺源, 列: 年份/预测人数/最小值/均值/最大值/行业平均数) ──
    df_eps = try_ak(ak.stock_profit_forecast_ths, symbol=code)
    if df_eps is not None and not df_eps.empty:
        year_col = df_eps.columns[0]
        latest_year = df_eps[year_col].max()
        row = df_eps[df_eps[year_col] == latest_year].iloc[0]
        out["earnings_forecast"] = {
            "预测年度": str(latest_year),
            "分析师数量": int(row.iloc[1]) if len(row) > 1 and row.iloc[1] else 0,
            "EPS预测均值(元)": to_num(row.iloc[3]) if len(row) > 3 else None,
            "EPS预测最小值": to_num(row.iloc[2]) if len(row) > 2 else None,
            "EPS预测最大值": to_num(row.iloc[4]) if len(row) > 4 else None,
        }
    else:
        out["earnings_forecast"] = {"分析师数量": 0}

    out["_status"] = "ok"
    return out
