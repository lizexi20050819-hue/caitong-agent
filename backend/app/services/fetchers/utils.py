"""Shared utilities for all A-share fetchers.

IMPORTANT: This module patches the system proxy on import to bypass Clash/SOCKS
proxies for Chinese financial data sources.  akshare internally uses requests
which inherits system proxy settings — this patch ensures domestic API calls
go directly without going through SOCKS proxy.
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from typing import Any

import pandas as pd
import requests

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
_TIMEOUT = 15

# ── Proxy bypass for Chinese financial data sources ─────────────────────────
# Clash/Sing-box SOCKS/TUN proxies block domestic financial API calls.
# We bypass the system proxy for all Chinese financial domains so that
# akshare (which uses requests internally) can reach them directly.

_FINANCIAL_DOMAINS = (
    "eastmoney.com,"
    "push2.eastmoney.com,"
    "eastmoney,"
    "dfcfw.com,"
    "10jqka.com.cn,"
    "sina.com.cn,"
    "sinaimg.cn,"
    "qq.com,"
    "gtimg.cn,"
    "xueqiu.com,"
    "cninfo.com.cn,"
    "hexun.com,"
    "tushare.pro,"
    "akshare,"
    "baostock,"
)


def _patch_proxy_for_finance() -> None:
    """Disable system proxy for all Chinese financial data domains."""
    existing = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    if _FINANCIAL_DOMAINS.strip() not in existing:
        new_no_proxy = f"{existing},{_FINANCIAL_DOMAINS}" if existing else _FINANCIAL_DOMAINS
        os.environ["NO_PROXY"] = new_no_proxy
        os.environ["no_proxy"] = new_no_proxy
        # Also unset explicit proxy env vars if they point to SOCKS
        for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            val = os.environ.get(var, "")
            if "socks" in val.lower():
                os.environ.pop(var, None)
                logger.info("Removed SOCKS proxy env var: %s=%s", var, val)


_patch_proxy_for_finance()


# ── safe wrappers ────────────────────────────────────────────────────────────

def safe_fetch(fn, default=None):
    """Wrap any fetch call — never raise, return default + error info."""
    try:
        return fn()
    except Exception as exc:
        logger.warning("%s failed: %s", getattr(fn, "__name__", "fetch"), exc)
        if isinstance(default, dict):
            return {"_error": str(exc), "_status": "failed", **default}
        return {"_error": str(exc), "_status": "failed"}


def to_num(value: Any) -> float | None:
    """Convert any value to float, returning None on failure."""
    if value is None:
        return None
    try:
        v = float(str(value).replace(",", "").replace("%", "").strip())
        if pd.isna(v):
            return None
        return round(v, 4)
    except (ValueError, TypeError):
        return None


def to_yi(value: Any) -> float | None:
    """Convert raw 元 to 亿 (divide by 1e8)."""
    n = to_num(value)
    return round(n / 1e8, 2) if n is not None else None


def to_pct(value: Any) -> float | None:
    """Parse percentage string like '18.7%' → 18.7."""
    if value is None:
        return None
    s = str(value).replace("%", "").strip()
    return to_num(s)


def safe_div(a: float | None, b: float | None) -> float | None:
    """Safely divide a / b, returning None on zero/None."""
    if a is None or b is None or b == 0:
        return None
    return round(a / b, 4)


def pct_change(old: float | None, new: float | None) -> float | None:
    """Percentage change from old to new."""
    if old is None or new is None or old == 0:
        return None
    return round((new / old - 1) * 100, 2)


# ── ticker helpers (A-share only) ────────────────────────────────────────────

def normalize_code(ticker: str) -> str:
    """Normalize any A-share ticker to 6-digit code."""
    return ticker.strip().upper().replace(".SS", "").replace(".SZ", "")[:6]


def to_baostock_code(code: str) -> str:
    """Convert 6-digit code to baostock format: sh.XXXXXX or sz.XXXXXX."""
    c = normalize_code(code)
    return f"sh.{c}" if c.startswith(("5", "6", "9")) else f"sz.{c}"


def eastmoney_secid(code: str) -> str:
    """Build eastmoney secid: market.code where market is 1=SH, 0=SZ."""
    c = normalize_code(code)
    market = "1" if c.startswith(("5", "6", "9")) else "0"
    return f"{market}.{c}"


# ── date helpers ─────────────────────────────────────────────────────────────

_TODAY = date.today()
_YEAR = _TODAY.year


def recent_years(n: int = 6) -> list[int]:
    """Last n fiscal years."""
    end = _YEAR - 1
    return list(range(end - n + 1, end + 1))


# ── column finder ────────────────────────────────────────────────────────────

def find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """Find the first matching column name in a dataframe."""
    for c in candidates:
        if c in df.columns:
            return c
    return None


def try_ak(func, *args, timeout: int = 10, **kwargs):
    """Call an akshare function with timeout, return None on failure.

    Uses a thread-based timeout to prevent hanging behind Clash proxy.
    """
    import threading

    result_container: list = []
    exception_container: list[Exception] = []

    def _target():
        try:
            r = func(*args, **kwargs)
            result_container.append(r)
        except Exception as e:
            exception_container.append(e)

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if t.is_alive():
        logger.debug("akshare %s timed out after %ds", getattr(func, "__name__", str(func)), timeout)
        return None  # still running — abandon

    if exception_container:
        logger.debug("akshare %s failed: %s", getattr(func, "__name__", str(func)), exception_container[0])
        return None

    if result_container:
        result = result_container[0]
        if result is not None and hasattr(result, "empty") and not result.empty:
            return result
        if isinstance(result, (list, dict)) and len(result) > 0:
            return result
    return None
