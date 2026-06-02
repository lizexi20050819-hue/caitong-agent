"""Dimension 4 · A-share 同业对标 — 同行业公司 PE/PB 分位对比.

Data: akshare stock_board_industry_cons_em + eastmoney push2.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from backend.app.services.fetchers.utils import (
    normalize_code,
    safe_fetch,
    to_num,
    try_ak,
)

logger = logging.getLogger(__name__)


def fetch_peers(ticker: str, industry: str = "", top_n: int = 10) -> dict[str, Any]:
    code = normalize_code(ticker)
    return safe_fetch(lambda: _fetch(code, industry, top_n), default={})


def _fetch(code: str, industry: str, top_n: int) -> dict:
    out: dict[str, Any] = {}
    import akshare as ak

    # 1. Target metrics (from eastmoney push2)
    target = _get_stock_metrics(code)
    out["target"] = target

    # 2. Find industry
    if not industry:
        df_info = try_ak(ak.stock_individual_info_em, symbol=code)
        if df_info is not None:
            try:
                df_info = df_info.set_index("item")
                if "行业" in df_info.index:
                    industry = str(df_info.loc["行业", "value"])
            except Exception:
                pass

    if not industry:
        out["peers"] = []
        out["peer_count"] = 0
        out["_status"] = "ok"
        return out

    # 3. Get peer list from industry board
    df_board = try_ak(ak.stock_board_industry_cons_em, symbol=industry)
    if df_board is None or "代码" not in df_board.columns:
        out["peers"] = []
        out["peer_count"] = 0
        out["_status"] = "ok"
        return out

    peer_codes = [c for c in df_board["代码"].astype(str).str.strip() if c != code]

    # 4. Get metrics for each peer (limit to 20 to avoid rate limiting)
    peer_metrics = []
    for pc in peer_codes[:20]:
        m = _get_stock_metrics(pc)
        if m.get("name"):
            peer_metrics.append({"code": pc, **m})

    # 5. PE/PB percentiles
    if target.get("pe_ttm"):
        pe_vals = sorted([p["pe_ttm"] for p in peer_metrics if p.get("pe_ttm") and p["pe_ttm"] > 0])
        if pe_vals and target["pe_ttm"] > 0:
            rank = sum(1 for v in pe_vals if v < target["pe_ttm"])
            out["pe_percentile"] = round(rank / len(pe_vals) * 100, 1)
            out["pe_median"] = round(float(np.median(pe_vals)), 2)

    if target.get("pb"):
        pb_vals = sorted([p["pb"] for p in peer_metrics if p.get("pb") and p["pb"] > 0])
        if pb_vals and target["pb"] > 0:
            rank = sum(1 for v in pb_vals if v < target["pb"])
            out["pb_percentile"] = round(rank / len(pb_vals) * 100, 1)
            out["pb_median"] = round(float(np.median(pb_vals)), 2)

    peer_metrics.sort(key=lambda p: p.get("market_cap") or 0, reverse=True)
    out["peers"] = peer_metrics[:top_n]
    out["peer_count"] = len(peer_metrics)
    out["_status"] = "ok"
    return out


def _get_stock_metrics(code: str) -> dict[str, Any]:
    """Get brief metrics via eastmoney push2."""
    try:
        import requests
        from backend.app.services.fetchers.utils import eastmoney_secid
        secid = eastmoney_secid(code)
        url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f57,f58,f43,f162,f167,f116,f170"
        r = requests.get(url, timeout=8, proxies={"http": None, "https": None},
                        headers={"User-Agent": "Mozilla/5.0"})
        data = r.json().get("data") or {}
        name = data.get("f58", code)
        price_raw = data.get("f43")

        def _pe(v):
            n = to_num(v)
            return round(n / 100, 2) if n and n > 100 else n

        return {
            "name": name if name and not name.isdigit() else code,
            "price": _pe(price_raw),
            "pe_ttm": _pe(data.get("f162")),
            "pb": _pe(data.get("f167")),
            "market_cap": to_num(data.get("f116")),
            "daily_change_pct": to_num(data.get("f170")),
        }
    except Exception:
        return {"name": code, "price": None, "pe_ttm": None, "pb": None, "market_cap": None}
