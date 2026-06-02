"""Dimension 21 · A-share 机构持仓 — 基金 / 十大流通股东."""

from __future__ import annotations

import logging
from typing import Any

from backend.app.services.fetchers.utils import normalize_code, safe_fetch, to_num, try_ak

logger = logging.getLogger(__name__)


def fetch_fund_holders(ticker: str) -> dict[str, Any]:
    code = normalize_code(ticker)
    return safe_fetch(lambda: _fetch(code), default={})


def _fetch(code: str) -> dict:
    out: dict[str, Any] = {}
    import akshare as ak

    # 1. 基金持仓 — akshare 1.18 renamed this to stock_report_fund_hold_detail
    df_fund = try_ak(ak.stock_report_fund_hold_detail, symbol=code, date="2025", timeout=10)
    funds = []
    if df_fund is not None:
        for _, r in df_fund.iterrows():
            funds.append({
                "fund_name": str(r.get("基金名称", r.get("fund_name", ""))),
                "fund_code": str(r.get("基金代码", r.get("fund_code", ""))),
                "shares": to_num(r.get("持仓数量") or r.get("持股数")),
                "market_value": to_num(r.get("持仓市值") or r.get("持股市值")),
            })
        funds.sort(key=lambda f: f.get("market_value") or 0, reverse=True)
    out["fund_holdings"] = {"total_funds": len(funds), "top_holdings": funds[:20]}

    # 2. 管理层持股 (replacement for stock_top_holders_em)
    df_mgmt = try_ak(ak.stock_hold_management_detail_em, symbol=code, timeout=10)
    out["top10_holders"] = []
    if df_mgmt is not None:
        for _, r in df_mgmt.head(10).iterrows():
            out["top10_holders"].append({
                "name": str(r.get("姓名", r.get("name", ""))),
                "position": str(r.get("职务", r.get("position", ""))),
                "shares": to_num(r.get("持股数量", r.get("shares"))),
            })

    # 3. 十大流通股东 — function removed in akshare 1.18; skip gracefully
    out["top10_float_holders"] = []

    # 4. 股东户数趋势 — try shareholder change data
    sc = {"current": None, "history": [], "trend": "无数据"}
    df_sh = try_ak(ak.stock_shareholder_change_ths, symbol=code, timeout=10)
    if df_sh is not None:
        from backend.app.services.fetchers.utils import find_col
        count_col = find_col(df_sh, ["股东户数", "股东人数"])
        date_col = find_col(df_sh, ["截止日期", "日期", "报告期"])
        if count_col and date_col:
            recent = df_sh.head(4)
            counts = [to_num(r[count_col]) for _, r in recent.iterrows()]
            dates = [str(r[date_col]) for _, r in recent.iterrows()]
            sc["current"] = counts[0]
            sc["history"] = [{"date": d, "count": c} for d, c in zip(dates, counts)]
            if len(counts) >= 2 and counts[0] and counts[-1]:
                if counts[0] < counts[-1] * 0.9:
                    sc["trend"] = "筹码集中"
                elif counts[0] > counts[-1] * 1.1:
                    sc["trend"] = "筹码分散"
                else:
                    sc["trend"] = "基本稳定"
    out["shareholder_count"] = sc
    out["_status"] = "ok"
    return out
