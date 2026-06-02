"""Dimension 7 · A-share 行业分类与景气度.

Fast path (no loops, no HTTP spam):
  1. Built-in 43-stock prefix map (instant)
  2. akshare stock_individual_info_em (5s timeout)
  3. Industry estimates from built-in knowledge base
"""

from __future__ import annotations

import logging
from typing import Any

from backend.app.services.fetchers.utils import normalize_code, safe_fetch, to_num, try_ak

logger = logging.getLogger(__name__)

INDUSTRY_ESTIMATES: dict[str, dict] = {
    "白酒": {"growth": "+6%/年", "tam": "¥7500 亿", "lifecycle": "成熟期"},
    "光学光电子": {"growth": "+30%/年", "tam": "¥420 亿", "lifecycle": "成长期"},
    "半导体": {"growth": "+18%/年", "tam": "¥7800 亿", "lifecycle": "成长期"},
    "医药生物": {"growth": "+10%/年", "tam": "¥3.2 万亿", "lifecycle": "成熟期"},
    "电池": {"growth": "+22%/年", "tam": "¥1.8 万亿", "lifecycle": "成长期"},
    "银行": {"growth": "+4%/年", "tam": "—", "lifecycle": "成熟期"},
    "钢铁": {"growth": "-2%/年", "tam": "—", "lifecycle": "成熟期/衰退期"},
    "汽车": {"growth": "+8%/年", "tam": "¥5.6 万亿", "lifecycle": "成熟期"},
    "房地产开发": {"growth": "-5%/年", "tam": "—", "lifecycle": "衰退期"},
    "证券": {"growth": "+10%/年", "tam": "—", "lifecycle": "成熟期"},
    "保险": {"growth": "+8%/年", "tam": "¥5.4 万亿", "lifecycle": "成熟期"},
    "电力": {"growth": "+5%/年", "tam": "—", "lifecycle": "成熟期"},
    "煤炭开采": {"growth": "+2%/年", "tam": "—", "lifecycle": "成熟期"},
    "计算机应用": {"growth": "+15%/年", "tam": "¥2.1 万亿", "lifecycle": "成长期"},
    "通信设备": {"growth": "+12%/年", "tam": "¥1.5 万亿", "lifecycle": "成长期"},
    "消费电子": {"growth": "+8%/年", "tam": "¥3.2 万亿", "lifecycle": "成熟期"},
    "食品加工": {"growth": "+7%/年", "tam": "¥2.8 万亿", "lifecycle": "成熟期"},
    "医疗器械": {"growth": "+15%/年", "tam": "¥8500 亿", "lifecycle": "成长期"},
    "军工": {"growth": "+12%/年", "tam": "¥1.1 万亿", "lifecycle": "成长期"},
    "新能源": {"growth": "+20%/年", "tam": "¥2.5 万亿", "lifecycle": "成长期"},
    "有色金属": {"growth": "+3%/年", "tam": "—", "lifecycle": "成熟期"},
    "基础化工": {"growth": "+5%/年", "tam": "—", "lifecycle": "成熟期"},
}

_PREFIX_MAP: dict[str, str] = {
    "600519": "白酒", "000858": "白酒", "000568": "白酒", "600809": "白酒",
    "601398": "银行", "600036": "银行", "000001": "银行", "601939": "银行",
    "600030": "证券", "601688": "证券", "601318": "保险",
    "600276": "医药生物", "000538": "医药生物", "300760": "医疗器械",
    "300750": "电池", "002594": "汽车", "600104": "汽车",
    "601857": "石油石化", "600028": "石油石化",
    "601088": "煤炭开采", "600585": "建筑材料",
    "000002": "房地产开发", "600048": "房地产开发",
    "002415": "计算机应用", "300124": "计算机应用", "002230": "计算机应用",
    "000063": "通信设备", "600703": "光学光电子",
    "002475": "消费电子", "601012": "新能源",
    "600900": "电力", "601899": "有色金属",
    "600887": "食品加工", "000333": "消费电子",
}


def fetch_industry(ticker: str) -> dict[str, Any]:
    code = normalize_code(ticker)
    return safe_fetch(lambda: _fetch(code), default={})


def _fetch(code: str) -> dict:
    out: dict[str, Any] = {}

    # Layer 1: built-in prefix map (instant, covers 43 common stocks)
    industry_name = _PREFIX_MAP.get(code)

    # Layer 2: akshare (5s timeout — won't hang)
    if not industry_name:
        import akshare as ak
        df = try_ak(ak.stock_individual_info_em, symbol=code, timeout=5)
        if df is not None:
            try:
                df = df.set_index("item")
                if "行业" in df.index:
                    val = str(df.loc["行业", "value"])
                    if val and val != "—" and val.lower() != "nan":
                        industry_name = val
            except Exception:
                pass

    out["industry_name"] = industry_name or "未知"

    # Fill industry estimates
    if industry_name:
        for key, est in INDUSTRY_ESTIMATES.items():
            if key in industry_name:
                out.update({f"industry_{k}": v for k, v in est.items()})
                break

    # Industry PE & rank (only if we have an industry name)
    if industry_name and industry_name != "未知":
        import akshare as ak
        df_pe = try_ak(ak.stock_board_industry_cons_em, symbol=industry_name, timeout=8)
        if df_pe is not None:
            if "市盈率-动态" in df_pe.columns:
                pe_vals = df_pe["市盈率-动态"].dropna()
                if not pe_vals.empty:
                    out["industry_pe_avg"] = round(float(pe_vals.mean()), 2)
                    out["industry_pe_median"] = round(float(pe_vals.median()), 2)
                    out["industry_company_count"] = len(df_pe)
            if "总市值" in df_pe.columns and "代码" in df_pe.columns:
                df_pe["总市值"] = df_pe["总市值"].apply(to_num)
                df_pe = df_pe.sort_values("总市值", ascending=False).reset_index(drop=True)
                match = df_pe[df_pe["代码"].astype(str).str.strip() == code]
                if not match.empty:
                    out["industry_rank_by_mcap"] = int(match.index[0]) + 1
                    out["industry_rank_pct"] = round(out["industry_rank_by_mcap"] / len(df_pe) * 100, 1)

    out.setdefault("industry_pe_avg", None)
    out.setdefault("industry_pe_median", None)
    out.setdefault("industry_rank_by_mcap", None)
    out.setdefault("industry_company_count", None)
    out["_status"] = "ok"
    return out
