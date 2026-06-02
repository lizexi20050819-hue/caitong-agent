"""Dimension 15 · A-share 事件催化剂 — 分红预告 / 限售解禁 / 公告."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from backend.app.services.fetchers.utils import normalize_code, safe_fetch, try_ak

logger = logging.getLogger(__name__)


def fetch_events(ticker: str) -> dict[str, Any]:
    code = normalize_code(ticker)
    return safe_fetch(lambda: _fetch(code), default={})


def _fetch(code: str) -> dict:
    out: dict[str, Any] = {"upcoming": [], "past_recent": []}
    import akshare as ak

    today = date.today()

    # 1. Dividend announcements (most reliable event data for A-shares)
    df_div = try_ak(ak.stock_history_dividend_detail, symbol=code, indicator="分红", timeout=10)
    if df_div is not None:
        for _, r in df_div.head(5).iterrows():
            plan_date = str(r.get("预案公告日", r.get("公告日期", "")))
            if plan_date and plan_date >= today.strftime("%Y%m%d"):
                out["upcoming"].append({
                    "date": plan_date,
                    "event": f"分红预案: {r.get('派息', '—')}",
                    "impact": "medium",
                    "days_away": None,
                })

    # 2. Stock notices (recent announcements)
    df_notice = try_ak(ak.stock_notice_report, symbol=code, timeout=10)
    if df_notice is not None and "标题" in df_notice.columns:
        for _, r in df_notice.head(10).iterrows():
            title = str(r.get("标题", ""))
            notice_date = str(r.get("日期", r.get("公告日期", "")))
            # Classify by title keywords
            impact = "low"
            if any(kw in title for kw in ["年报", "中报", "季报", "解禁", "增发", "重组", "并购"]):
                impact = "high"
            elif any(kw in title for kw in ["股东大会", "分红", "除权", "业绩预告", "回购"]):
                impact = "medium"
            out["upcoming"].append({
                "date": notice_date,
                "event": title[:100],
                "impact": impact,
                "days_away": None,
            })

    # 3. Restricted shares release (解禁)
    df_rs = try_ak(ak.stock_restricted_release_summary_em, symbol="近一年", timeout=10)
    if df_rs is not None:
        from backend.app.services.fetchers.utils import find_col
        code_col = find_col(df_rs, ["股票代码", "代码"])
        if code_col:
            rows = df_rs[df_rs[code_col].astype(str).str.strip() == code]
            for _, r in rows.iterrows():
                rel_date = str(r.get("解禁日期", ""))
                try:
                    rd = date.fromisoformat(rel_date[:10])
                    days = (rd - today).days
                except (ValueError, TypeError):
                    days = None
                if days is not None and days >= 0:
                    out["upcoming"].append({
                        "date": rel_date,
                        "event": f"限售解禁: {r.get('解禁数量', '—')} 股",
                        "impact": "high",
                        "days_away": days,
                    })

    # Sort by days_away
    out["upcoming"].sort(
        key=lambda e: e.get("days_away") if e.get("days_away") is not None else 999
    )
    out["_status"] = "ok"
    return out
