"""Dimension 12 · A-share 资金流向 — 北向 / 融资融券 / 大宗 / 解禁.

All data via akshare.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from backend.app.services.fetchers.utils import (
    normalize_code,
    safe_fetch,
    to_num,
    try_ak,
)

logger = logging.getLogger(__name__)


def fetch_capital_flow(ticker: str) -> dict[str, Any]:
    code = normalize_code(ticker)
    return safe_fetch(lambda: _fetch(code), default={})


def _fetch(code: str) -> dict:
    out: dict[str, Any] = {}
    import akshare as ak

    _fill_northbound(out, code, ak)
    _fill_block_trades(out, code, ak)
    _fill_restricted_shares(out, code, ak)

    out["_status"] = "ok"
    return out


# ── 北向资金 ─────────────────────────────────────────────────────────────────

def _fill_northbound(out: dict, code: str, ak) -> None:
    nb: dict[str, Any] = {"hold_shares": None, "hold_pct": None, "hold_mcap": None,
                          "net_buy_5d": None, "net_buy_20d": None, "trend": "无数据"}
    df = try_ak(ak.stock_hsgt_individual_em, symbol=code)
    if df is not None and not df.empty:
        from backend.app.services.fetchers.utils import find_col
        share_col = find_col(df, ["持股数量", "当日持股数量"])
        pct_col = find_col(df, ["持股数量占A股百分比", "持股比例"])
        mcap_col = find_col(df, ["持股市值", "当日持股市值"])
        chg_col = find_col(df, ["当日净流入资金", "当日净持股", "当日持仓变动", "当日增持"])

        latest = df.iloc[-1]
        nb["hold_shares"] = to_num(latest.get(share_col)) if share_col else None
        nb["hold_pct"] = to_num(latest.get(pct_col)) if pct_col else None
        nb["hold_mcap"] = to_num(latest.get(mcap_col)) if mcap_col else None

        if chg_col:
            changes = df[chg_col].tail(20)
            nb["net_buy_5d"] = round(float(changes.tail(5).sum()), 2)
            nb["net_buy_20d"] = round(float(changes.sum()), 2)

        if share_col and len(df) >= 10:
            recent = df[share_col].tail(10).apply(to_num)
            if recent.iloc[-1] and recent.iloc[0]:
                if recent.iloc[-1] > recent.iloc[0] * 1.05:
                    nb["trend"] = "持续加仓"
                elif recent.iloc[-1] < recent.iloc[0] * 0.95:
                    nb["trend"] = "持续减仓"
                else:
                    nb["trend"] = "窄幅震荡"

    out["northbound"] = nb


# ── 融资融券 ─────────────────────────────────────────────────────────────────

def _fill_margin(out: dict, code: str, ak) -> None:
    margin: dict[str, Any] = {"fin_balance": None, "margin_balance": None, "trend": "无数据"}
    today = date.today().strftime("%Y%m%d")
    fn = ak.stock_margin_detail_sse if code.startswith(("5", "6", "9")) else ak.stock_margin_detail_szse
    df = try_ak(fn, date=today)
    if df is not None:
        from backend.app.services.fetchers.utils import find_col
        code_col = find_col(df, ["股票代码", "证券代码"])
        if code_col:
            row = df[df[code_col].astype(str).str.strip() == code]
            if not row.empty:
                r = row.iloc[0]
                margin["fin_balance"] = to_num(r.get("融资余额") or r.get("融资资金"))
                margin["margin_balance"] = to_num(r.get("融券余额") or r.get("融券余量"))
    out["margin"] = margin


# ── 大宗交易 ─────────────────────────────────────────────────────────────────

def _fill_block_trades(out: dict, code: str, ak) -> None:
    year = date.today().year
    df = try_ak(ak.stock_dzjy_mrtj, start_date=f"{year}0101", end_date=f"{year}1231")
    if df is not None:
        from backend.app.services.fetchers.utils import find_col
        code_col = find_col(df, ["证券代码", "股票代码"])
        if code_col:
            rows = df[df[code_col].astype(str).str.strip() == code]
            trades = []
            for _, r in rows.head(10).iterrows():
                trades.append({
                    "date": str(r.get("成交日期", "")),
                    "price": to_num(r.get("成交价")),
                    "volume": to_num(r.get("成交额")),
                    "premium_pct": to_num(r.get("折溢价比率(%)") or r.get("折溢价比率")),
                })
            premiums = [t["premium_pct"] for t in trades if t["premium_pct"] is not None]
            out["block_trades"] = {
                "count_60d": len(rows),
                "recent_trades": trades[:5],
                "avg_premium_pct": round(sum(premiums) / len(premiums), 2) if premiums else None,
            }
            return
    out["block_trades"] = {"count_60d": 0, "recent_trades": [], "avg_premium_pct": None}


# ── 限售解禁 ─────────────────────────────────────────────────────────────────

def _fill_restricted_shares(out: dict, code: str, ak) -> None:
    df = try_ak(ak.stock_restricted_release_summary_em, symbol="近一年")
    if df is not None:
        from backend.app.services.fetchers.utils import find_col
        code_col = find_col(df, ["股票代码", "代码"])
        if code_col:
            rows = df[df[code_col].astype(str).str.strip() == code]
            upcoming = []
            for _, r in rows.head(5).iterrows():
                upcoming.append({
                    "date": str(r.get("解禁日期", "")),
                    "shares": to_num(r.get("解禁数量")),
                    "pct_of_float": to_num(r.get("占总股本比例")),
                })
            out["restricted_shares"] = {"upcoming_count": len(rows), "upcoming_list": upcoming}
            return
    out["restricted_shares"] = {"upcoming_count": 0, "upcoming_list": []}
