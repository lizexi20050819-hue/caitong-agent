"""A-share market data: baostock K-line + eastmoney real-time snapshot.

Primary: baostock (TCP, works behind Clash TUN proxy)
Fallback: eastmoney push2 HTTP (may be blocked)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
import requests

from backend.app.models import MarketSnapshot
from backend.app.services.fetchers.utils import (
    eastmoney_secid,
    normalize_code,
    to_baostock_code,
    to_num,
    _HEADERS,
    _TIMEOUT,
)

# ── public API ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MarketData:
    snapshot: MarketSnapshot
    history: pd.DataFrame


def fetch_market_data(raw_ticker: str, period: str = "1y") -> MarketData:
    """Fetch A-share market data: K-line + real-time snapshot."""
    code = normalize_code(raw_ticker)
    bs_code = to_baostock_code(code)

    # 1. baostock K-line
    history, bs_name = _fetch_baostock_history(bs_code)

    # 2. eastmoney real-time snapshot (best-effort)
    realtime = _fetch_eastmoney_realtime(code)

    # 3. derive snapshot
    latest_price = realtime.get("price")
    if latest_price is None and "Close" in history and not history.empty:
        latest_price = _last_float(history["Close"])

    previous_close = realtime.get("previous_close")
    if previous_close is None and "Close" in history and len(history) > 1:
        previous_close = _second_last_float(history["Close"])

    daily_change_pct = None
    if latest_price and previous_close and previous_close != 0:
        daily_change_pct = round((latest_price / previous_close - 1) * 100, 2)

    pe_ttm = realtime.get("pe_ttm")
    if pe_ttm is None and "peTTM" in history and not history.empty:
        pe_ttm = _last_float(history["peTTM"])

    pb = realtime.get("pb")
    if pb is None and "pbMRQ" in history and not history.empty:
        pb = _last_float(history["pbMRQ"])

    # name priority: eastmoney > baostock > code
    name = realtime.get("name") or bs_name or code
    if name and name.isdigit():
        name = bs_name or code

    snapshot = MarketSnapshot(
        input_ticker=raw_ticker,
        resolved_ticker=f"{code}.{'SS' if code.startswith(('5','6','9')) else 'SZ'}",
        name=name,
        latest_price=latest_price,
        previous_close=previous_close,
        daily_change_pct=daily_change_pct,
        market_cap=realtime.get("market_cap"),
        pe_ttm=pe_ttm,
        pb=pb,
        roe=None,
        data_points=len(history),
    )
    return MarketData(snapshot=snapshot, history=history)


# ── baostock ─────────────────────────────────────────────────────────────────


def _fetch_baostock_history(bs_code: str) -> tuple[pd.DataFrame, str | None]:
    """Return (history_df, stock_name)."""
    try:
        import baostock as bs

        end_date = date.today()
        start_date = end_date - timedelta(days=430)

        lg = bs.login()
        if lg.error_code != "0":
            bs.logout()
            return _empty_history(), None

        # Get stock name
        name = None
        try:
            rs_name = bs.query_stock_basic(code=bs_code)
            df_name = rs_name.get_data()
            if not df_name.empty and "code_name" in df_name.columns:
                name = str(df_name["code_name"].iloc[0]).strip() or None
        except Exception:
            pass

        # Get daily K-line
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,volume,peTTM,pbMRQ",
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d"),
            frequency="d",
            adjustflag="3",
        )
        df = rs.get_data()
        bs.logout()
    except Exception:
        return _empty_history(), None

    if df.empty:
        return _empty_history(), name

    df = df.rename(columns={
        "date": "Date", "open": "Open", "high": "High",
        "low": "Low", "close": "Close", "volume": "Volume",
    })
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"]).set_index("Date")
    for col in ["Open", "High", "Low", "Close", "Volume", "peTTM", "pbMRQ"]:
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["Close"]) if "Close" in df else df, name


# ── eastmoney real-time ─────────────────────────────────────────────────────


def _fetch_eastmoney_realtime(code: str) -> dict:
    """Eastmoney push2 real-time snapshot (best-effort, may fail behind proxy)."""
    try:
        secid = eastmoney_secid(code)
        fields = "f57,f58,f43,f44,f45,f116,f162,f167"
        url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields={fields}"
        r = requests.get(
            url, headers=_HEADERS, timeout=_TIMEOUT,
            proxies={"http": None, "https": None},
        )
        data = r.json().get("data") or {}
        price_raw = data.get("f43")
        pre_close_raw = data.get("f45")
        return {
            "name": data.get("f58", code),
            "price": _parse_em_num(price_raw, divisor=100.0),
            "previous_close": _parse_em_num(pre_close_raw, divisor=100.0),
            "market_cap": to_num(data.get("f116")),
            "pe_ttm": _parse_em_num(data.get("f162"), divisor=100.0),
            "pb": _parse_em_num(data.get("f167"), divisor=100.0),
        }
    except Exception:
        return {}


def _parse_em_num(raw, divisor: float = 1.0) -> float | None:
    """Parse eastmoney number (often scaled)."""
    try:
        v = float(raw)
        if divisor != 1.0 and v > 10000:
            v = v / divisor
        return round(v, 4)
    except (TypeError, ValueError):
        return None


# ── helpers ──────────────────────────────────────────────────────────────────


def _empty_history() -> pd.DataFrame:
    return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])


def _last_float(series: pd.Series) -> float | None:
    if series.empty:
        return None
    return to_num(series.dropna().iloc[-1])


def _second_last_float(series: pd.Series) -> float | None:
    cleaned = series.dropna()
    if len(cleaned) < 2:
        return None
    return to_num(cleaned.iloc[-2])
