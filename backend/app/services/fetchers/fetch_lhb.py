"""Dimension 16 · A-share 龙虎榜 — 上榜记录 / 机构 vs 游资博弈."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from backend.app.services.fetchers.utils import normalize_code, safe_fetch, to_num, try_ak

logger = logging.getLogger(__name__)

_INST_KEYWORDS = ["机构专用", "深股通专用", "沪股通专用"]


def fetch_lhb(ticker: str) -> dict[str, Any]:
    code = normalize_code(ticker)
    return safe_fetch(lambda: _fetch(code), default={})


def _fetch(code: str) -> dict:
    out: dict[str, Any] = {"appearances": [], "inst_vs_youzi": {}}
    import akshare as ak

    today = date.today()
    start = (today - timedelta(days=30)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")

    df = try_ak(ak.stock_lhb_detail_em, start_date=start, end_date=end)
    if df is None:
        out["_status"] = "ok"
        return out

    from backend.app.services.fetchers.utils import find_col
    code_col = find_col(df, ["代码", "股票代码"])
    if not code_col:
        out["_status"] = "ok"
        return out

    rows = df[df[code_col].astype(str).str.strip() == code]
    if rows.empty:
        out["_status"] = "ok"
        return out

    all_seats = []
    for _, r in rows.iterrows():
        seat = str(r.get("营业部名称", ""))
        buy = to_num(r.get("买入金额") or r.get("买入额"))
        sell = to_num(r.get("卖出金额") or r.get("卖出额"))
        net = ((buy or 0) - (sell or 0)) if (buy or sell) else None
        all_seats.append({
            "date": str(r.get("上榜日期", r.get("日期", ""))),
            "seat": seat, "buy": buy, "sell": sell, "net": net,
            "reason": str(r.get("上榜原因", "")),
        })

    by_date = defaultdict(list)
    for s in all_seats:
        by_date[s["date"]].append(s)

    for d, seats in sorted(by_date.items()):
        total_buy = sum((s["buy"] or 0) for s in seats)
        total_sell = sum((s["sell"] or 0) for s in seats)
        inst_buy = sum((s["buy"] or 0) for s in seats if any(kw in s["seat"] for kw in _INST_KEYWORDS))
        out["appearances"].append({
            "date": d,
            "total_buy": round(total_buy, 2),
            "total_sell": round(total_sell, 2),
            "net": round(total_buy - total_sell, 2),
            "inst_share": round(inst_buy / total_buy * 100, 1) if total_buy > 0 else 0,
            "seat_count": len(seats),
        })

    total_inst = sum((s["buy"] or 0) for s in all_seats if any(kw in s["seat"] for kw in _INST_KEYWORDS))
    total_youzi = sum((s["buy"] or 0) for s in all_seats if not any(kw in s["seat"] for kw in _INST_KEYWORDS))
    total_all = total_inst + total_youzi
    out["inst_vs_youzi"] = {
        "institutional_buy": round(total_inst, 2),
        "youzi_buy": round(total_youzi, 2),
        "inst_pct": round(total_inst / total_all * 100, 1) if total_all > 0 else 0,
        "verdict": (
            "机构主导" if total_inst > total_youzi * 1.5
            else "游资博弈" if total_youzi > total_inst * 1.5
            else "机构游资混战"
        ) if total_all > 0 else "无龙虎榜数据",
    }
    out["_status"] = "ok"
    return out
