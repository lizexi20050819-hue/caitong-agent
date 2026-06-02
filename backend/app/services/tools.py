"""LangChain tools — stock lookup + data fetchers + investor role-play.

Agent uses these as its "hands and eyes" to gather data and
role-play investors.  Agent decides WHICH tools to call and
interprets results — tools just return raw facts.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from backend.app.services.fetchers import (
    fetch_capital_flow,
    fetch_financials,
    fetch_industry,
    fetch_lhb,
    fetch_research,
    fetch_valuation,
)
from backend.app.services.market_data import fetch_market_data

# Cache for stock + fund name → code mapping (loaded once each)
_stock_map: dict[str, str] | None = None
_fund_map: dict[str, list[dict]] | None = None  # name → [{code, name, type}]


def _load_stock_map() -> dict[str, str]:
    """Load 5000+ A-share stock name→code (cached)."""
    global _stock_map
    if _stock_map is not None:
        return _stock_map
    try:
        import akshare as ak
        df = ak.stock_info_a_code_name()
        _stock_map = dict(zip(df["name"].astype(str).str.strip(), df["code"].astype(str).str.strip()))
    except Exception:
        _stock_map = {}
    return _stock_map


def _load_fund_map() -> dict[str, list[dict]]:
    """Load 26000+ fund name→[{code, name, type}] (cached)."""
    global _fund_map
    if _fund_map is not None:
        return _fund_map
    try:
        import akshare as ak
        df = ak.fund_name_em()
        _fund_map = {}
        for _, r in df.iterrows():
            code = str(r.iloc[0]).strip()
            name = str(r.iloc[2]).strip()
            ftype = str(r.iloc[3]).strip()
            if code and name:
                _fund_map.setdefault(name, []).append({"code": code, "name": name, "type": ftype})
    except Exception:
        _fund_map = {}
    return _fund_map


def _search_map(name: str, mapping: dict, kind: str) -> list[dict]:
    """Search a name→value(s) mapping, returning matches."""
    matches = []
    for entry_name, value in mapping.items():
        if name in entry_name:
            if isinstance(value, list):
                for v in value:
                    matches.append({**v, "security_type": kind})
            else:
                matches.append({"code": value, "name": entry_name, "security_type": kind})
        elif len(name) >= 2 and all(ch in entry_name for ch in name):
            if isinstance(value, list):
                for v in value:
                    matches.append({**v, "security_type": kind})
            else:
                matches.append({"code": value, "name": entry_name, "security_type": kind})
    return matches


# ═══════════════════════════════════════════════════════════════════════════
#  CODE LOOKUP — find stock or fund code from name
# ═══════════════════════════════════════════════════════════════════════════

@tool
def resolve_stock_code(name: str) -> dict[str, Any]:
    """根据股票/基金名称或简称查找 A 股代码。

    支持：个股（如"茅台"→600519）和场内基金（如"沪深300ETF"→510300）。
    返回结果中 security_type 标记为 "stock" 或 "fund"。

    用于：用户说名称时，先调这个工具找到 6 位代码，再用相应工具拉数据。
    必须先用这个工具找到准确的代码后，才能调用数据工具。

    Args:
        name: 股票/基金名称或简称，如"贵州茅台"、"茅台"、"沪深300ETF"、"510300"
    """
    name = name.strip()

    # If user typed a 6-digit code directly, check what it is
    if name.isdigit() and len(name) == 6:
        return _lookup_by_code(name)

    # Search stocks first, then funds
    stock_map = _load_stock_map()
    fund_map = _load_fund_map()

    stock_matches = _search_map(name, stock_map, "stock") if stock_map else []
    fund_matches = _search_map(name, fund_map, "fund") if fund_map else []

    # De-duplicate fund matches (same code appearing under different share classes)
    seen_codes = set()
    unique_funds = []
    for m in fund_matches:
        if m["code"] not in seen_codes:
            seen_codes.add(m["code"])
            unique_funds.append(m)
    fund_matches = unique_funds

    all_matches = stock_matches + fund_matches

    # Sort: stocks first, then ETFs (51/56/58 prefix), then other funds
    def _sort_key(m: dict) -> int:
        code = m.get("code", "")
        if m.get("security_type") == "stock":
            return 0
        if code[:2] in ("51", "56", "58"):  # exchange-traded ETF
            return 1
        return 2  # OTC fund / feeder fund

    all_matches.sort(key=_sort_key)
    # Deduplicate codes (keep first = highest priority)
    seen = set()
    unique = []
    for m in all_matches:
        if m["code"] not in seen:
            seen.add(m["code"])
            unique.append(m)

    if not unique:
        return {
            "error": f"未找到 '{name}'。请确认名称，或直接输入 6 位代码。",
            "hint": "如果是 ETF 请说完整名称，如'沪深300ETF'",
        }

    # Exact name match gets priority
    exact = [m for m in unique if m["name"] == name]
    if exact:
        return {"matched": exact[0], "candidates": unique[:10]}

    return {
        "matched": unique[0] if len(unique) == 1 else None,
        "candidates": unique[:15],
        "hint": "有多个匹配，请选一个。ETF 是 51/56/58 开头的代码。" if len(unique) > 1 else None,
    }


def _lookup_by_code(code: str) -> dict[str, Any]:
    """Check whether a 6-digit code is a stock or fund."""
    stock_map = _load_stock_map()
    fund_map = _load_fund_map()

    # Check stocks
    for name, scode in (stock_map or {}).items():
        if scode == code:
            return {
                "matched": {"code": code, "name": name, "security_type": "stock"},
                "note": "该代码为个股",
            }

    # Check funds
    for name, entries in (fund_map or {}).items():
        for entry in entries:
            if entry["code"] == code:
                return {
                    "matched": {"code": code, "name": entry["name"],
                                "type": entry["type"], "security_type": "fund"},
                    "note": f"该代码为{entry['type']}",
                }

    return {
        "matched": {"code": code, "name": code, "security_type": "unknown"},
        "note": "未在个股和基金表中找到该代码，可能是新股/新基金或代码有误",
    }


# ═══════════════════════════════════════════════════════════════════════════
#  ETF TOOLS — fund-specific data
# ═══════════════════════════════════════════════════════════════════════════

@tool
def get_etf_info(code: str) -> dict[str, Any]:
    """获取场内 ETF/LOF 实时行情和基本信息。

    返回：最新价、净值(IOPV)、折溢价率、成交额、规模(AUM)、份额。
    用于：判断 ETF 的流动性、定价是否合理。

    Args:
        code: 6位基金代码，如 510300
    """
    try:
        import akshare as ak
        df = ak.fund_etf_spot_em()
        row = df[df["代码"].astype(str).str.strip() == code.strip()]
        if row.empty:
            return {"error": f"未找到代码 {code} 的 ETF 实时数据"}

        r = row.iloc[0]
        def _v(key):
            try:
                return float(r.get(key, 0))
            except (ValueError, TypeError):
                return None

        iopv = _v("IOPV") or _v("单位净值")  # NAV
        price = _v("最新价")
        premium = None
        if iopv and price and iopv > 0:
            premium = round((price / iopv - 1) * 100, 2)

        return {
            "代码": code,
            "名称": str(r.get("名称", "")),
            "最新价": price,
            "净值(IOPV)": iopv,
            "折溢价率(%)": premium,
            "成交额(万元)": _v("成交额"),
            "成交量(手)": _v("成交量"),
            "流通市值(亿)": round(_v("流通值") / 1e8, 2) if _v("流通值") else None,
            "总份额(亿份)": round(_v("总份额") / 1e8, 2) if _v("总份额") else None,
            "日期": str(r.get("日期", "")),
        }
    except Exception as exc:
        return {"error": str(exc)}


@tool
def get_etf_holdings(code: str) -> dict[str, Any]:
    """获取 ETF 最新季度的前十大持仓和行业分布。

    返回：Top10 持仓（股票代码、名称、权重），行业配置比例。
    用于：穿透 ETF 看底层资产质量。

    Args:
        code: 6位基金代码，如 510300
    """
    try:
        import akshare as ak

        # 1. Top 10 holdings
        holdings = []
        df_h = ak.fund_portfolio_hold_em(symbol=code.strip(), date="2025")
        if df_h is not None and not df_h.empty:
            for _, r in df_h.head(10).iterrows():
                holdings.append({
                    "排名": int(r.iloc[0]) if r.iloc[0] else None,
                    "股票代码": str(r.iloc[1]),
                    "股票名称": str(r.iloc[2]),
                    "占净值比(%)": float(r.iloc[3]) if r.iloc[3] else None,
                    "持仓市值(万元)": float(r.iloc[5]) if len(r) > 5 and r.iloc[5] else None,
                })

        # 2. Sector allocation (best-effort)
        sectors = []
        try:
            df_s = ak.fund_report_industry_allocation_cninfo(code=code.strip())
            if df_s is not None and not df_s.empty:
                for _, r in df_s.head(10).iterrows():
                    sectors.append({
                        "行业": str(r.iloc[0]) if len(r) > 0 else "",
                        "占净值比(%)": float(r.iloc[1]) if len(r) > 1 and r.iloc[1] else None,
                    })
        except Exception:
            pass  # sector data is optional

        return {
            "代码": code,
            "持仓截止期": str(df_h.iloc[0].iloc[-1]) if df_h is not None and not df_h.empty else "未知",
            "前十大持仓": holdings,
            "行业分布": sectors,
            "前十大集中度(%)": round(sum(h.get("占净值比(%)", 0) or 0 for h in holdings), 2) if holdings else None,
        }
    except Exception as exc:
        return {"error": str(exc)}


@tool
def get_etf_performance(code: str) -> dict[str, Any]:
    """获取 ETF 近期收益和跟踪表现。

    返回：近1月/3月/6月/1年净值涨跌幅、年化跟踪误差（如有）。
    用于：评估 ETF 的收益表现和跟踪效果。

    Args:
        code: 6位基金代码，如 510300
    """
    try:
        import akshare as ak
        from datetime import date, timedelta

        today = date.today()
        end = today.strftime("%Y%m%d")

        # 1Y NAV history
        start_1y = (today - timedelta(days=370)).strftime("%Y%m%d")
        df = ak.fund_etf_fund_info_em(fund=code.strip(), start_date=start_1y, end_date=end)
        if df is None or df.empty:
            return {"error": f"未获取到 {code} 的历史净值数据"}

        # Find NAV column
        nav_col = next((c for c in df.columns if "单位净值" in str(c)), None)
        if nav_col is None:
            return {"error": "未找到净值列"}

        df[nav_col] = df[nav_col].apply(
            lambda x: float(x) if x and str(x).replace(".", "").replace("-", "").isdigit() else None
        )
        df = df.dropna(subset=[nav_col])
        df = df.sort_values(df.columns[0])  # date column

        def _period_return(days: int) -> float | None:
            if len(df) < 2:
                return None
            cutoff = today - timedelta(days=days)
            df_d = df.copy()
            # Filter to approximate cutoff
            navs = df_d[nav_col].values
            if len(navs) < 2:
                return None
            recent = navs[-1]
            if days <= 30 and len(navs) >= days:
                old = navs[-days]
            elif days <= 90 and len(navs) >= days:
                old = navs[-days]
            elif days <= 180 and len(navs) >= days:
                old = navs[-days]
            elif len(navs) >= min(days, 250):
                old = navs[-min(days, 250)]
            else:
                old = navs[0]
            if old and old > 0:
                return round((recent / old - 1) * 100, 2)
            return None

        # Daily returns for volatility (used as tracking error proxy)
        daily_returns = []
        nav_values = df[nav_col].values
        for i in range(1, len(nav_values)):
            if nav_values[i] and nav_values[i - 1] and nav_values[i - 1] > 0:
                daily_returns.append(nav_values[i] / nav_values[i - 1] - 1)

        volatility_annual = None
        if daily_returns:
            import math
            std = sum((r - sum(daily_returns) / len(daily_returns)) ** 2 for r in daily_returns) / len(daily_returns)
            volatility_annual = round(math.sqrt(std) * math.sqrt(252) * 100, 2)

        return {
            "代码": code,
            "最新净值": nav_values[-1] if len(nav_values) > 0 else None,
            "净值日期": str(df.iloc[-1, 0]) if len(df) > 0 else "",
            "近1月涨跌幅(%)": _period_return(22),
            "近3月涨跌幅(%)": _period_return(66),
            "近6月涨跌幅(%)": _period_return(132),
            "近1年涨跌幅(%)": _period_return(252),
            "年化波动率(%)": volatility_annual,
            "数据说明": "跟踪误差需与基准指数对比，本字段为净值年化波动率作为替代参考",
        }
    except Exception as exc:
        return {"error": str(exc)}


# ═══════════════════════════════════════════════════════════════════════════
#  DATA TOOLS — return raw numbers, no interpretation
# ═══════════════════════════════════════════════════════════════════════════

@tool
def get_market_data(ticker: str) -> dict[str, Any]:
    """获取 A 股实时行情。返回价格、涨跌幅、PE(TTM)、PB、K线数据点数。"""
    data = fetch_market_data(ticker)
    snap = data.snapshot
    return {
        "名称": snap.name,
        "代码": snap.resolved_ticker,
        "最新价": snap.latest_price,
        "涨跌幅%": snap.daily_change_pct,
        "PE(TTM)": snap.pe_ttm,
        "PB": snap.pb,
        "数据点数": snap.data_points,
    }


@tool
def get_financials(ticker: str) -> dict[str, Any]:
    """获取 A 股财务数据。返回 ROE、净利率、毛利率、营收增速、负债率、流动比、速动比、ROIC、6年营收/利润历史、股息率、分红记录。"""
    data = fetch_market_data(ticker)
    price = data.snapshot.latest_price
    fin = fetch_financials(ticker, price)
    fh = fin.get("financial_health", {})
    return {
        "ROE(%)": fin.get("roe"),
        "ROE历史": fin.get("roe_history"),
        "净利率(%)": fin.get("net_margin"),
        "毛利率(%)": fin.get("gross_margin"),
        "营收增速(%)": fin.get("revenue_growth"),
        "营收历史(亿)": fin.get("revenue_history"),
        "净利润历史(亿)": fin.get("net_profit_history"),
        "年份": fin.get("financial_years"),
        "资产负债率(%)": fh.get("debt_ratio"),
        "流动比率": fh.get("current_ratio"),
        "速动比率": fh.get("quick_ratio"),
        "ROIC(%)": fh.get("roic"),
        "股息率(%)": (fin.get("dividend_yields") or [None])[-1],
        "分红记录(元/10股)": fin.get("dividend_amounts"),
    }


@tool
def get_valuation(ticker: str) -> dict[str, Any]:
    """获取估值分位。返回 PE/PB 当前值和 5 年历史分位（最低/最高/中位/当前处于多少%分位）。用于判断估值贵不贵。"""
    val = fetch_valuation(ticker)
    return {
        "PE(TTM)": val.get("pe_ttm"),
        "PB": val.get("pb"),
        "PE_5年最低": val.get("pe_5y_min"),
        "PE_5年最高": val.get("pe_5y_max"),
        "PE_5年中位": val.get("pe_5y_median"),
        "PE_当前分位(%)": val.get("pe_historical_percentile"),
        "PB_5年最低": val.get("pb_5y_min"),
        "PB_5年最高": val.get("pb_5y_max"),
        "PB_当前分位(%)": val.get("pb_historical_percentile"),
    }


@tool
def get_industry(ticker: str) -> dict[str, Any]:
    """获取行业分类和景气度。返回行业名称、生命周期、增速、市值排名。"""
    ind = fetch_industry(ticker)
    return {
        "行业": ind.get("industry_name"),
        "生命周期": ind.get("industry_lifecycle"),
        "行业增速": ind.get("industry_growth"),
        "TAM": ind.get("industry_tam"),
        "行业内市值排名": ind.get("industry_rank_by_mcap"),
        "行业内公司数": ind.get("industry_company_count"),
        "行业PE均值": ind.get("industry_pe_avg"),
    }


@tool
def get_capital_flow(ticker: str) -> dict[str, Any]:
    """获取资金面数据。返回北向资金持股比例、趋势、大宗交易、限售解禁。"""
    cf = fetch_capital_flow(ticker)
    nb = cf.get("northbound", {})
    bt = cf.get("block_trades", {})
    rs = cf.get("restricted_shares", {})
    return {
        "北向持股比例(%)": nb.get("hold_pct"),
        "北向趋势": nb.get("trend"),
        "北向持股市值": nb.get("hold_mcap"),
        "近60日大宗交易笔数": bt.get("count_60d"),
        "待解禁批次": rs.get("upcoming_count"),
    }


@tool
def get_research(ticker: str) -> dict[str, Any]:
    """获取券商研报共识。返回覆盖券商数、共识评级、评级分布、盈利预测EPS。"""
    res = fetch_research(ticker)
    rs = res.get("rating_summary", {})
    ef = res.get("earnings_forecast", {})
    return {
        "覆盖券商数": rs.get("total", 0),
        "共识评级": rs.get("consensus", ""),
        "买入/增持/中性/减持/卖出": f"{rs.get('buy',0)}/{rs.get('overweight',0)}/{rs.get('hold',0)}/{rs.get('underweight',0)}/{rs.get('sell',0)}",
        "盈利预测": {
            "年度": ef.get("预测年度"),
            "分析师数": ef.get("分析师数量"),
            "EPS均值(元)": ef.get("EPS预测均值(元)"),
            "EPS范围": f"{ef.get('EPS预测最小值')} ~ {ef.get('EPS预测最大值')}",
        },
    }


@tool
def get_lhb_data(ticker: str) -> dict[str, Any]:
    """获取龙虎榜数据。返回近30日上榜次数、机构vs游资买卖金额比例。"""
    lhb = fetch_lhb(ticker)
    return {
        "近30日上榜次数": len(lhb.get("appearances", [])),
        "博弈格局": lhb.get("inst_vs_youzi", {}),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  INVESTOR TOOLS — each investor is a tool the Agent can call
#  The Agent passes the stock data and the investor evaluates it
# ═══════════════════════════════════════════════════════════════════════════

INVESTOR_PROMPTS = {
    "巴菲特": (
        "你是沃伦·巴菲特。你的投资原则：ROE>15%、负债率<50%、PE<25、连续分红、行业看得懂。"
        "请基于以下数据给出：1)评分(0-100) 2)看多/中性/看空 3)30字内的评语（用巴菲特的说话风格）。"
        "数据：{data}"
    ),
    "格雷厄姆": (
        "你是本杰明·格雷厄姆。你的原则：PE<15、PB<1.5、流动比率>2、极度分散、安全边际第一。"
        "请基于以下数据给出：1)评分 2)看多/中性/看空 3)30字评语（格雷厄姆风格）。"
        "数据：{data}"
    ),
    "段永平": (
        "你是段永平。你的原则：买股票就是买公司，ROE>15%、PE<30、只投看得懂的行业（消费/电子/互联网）、净利率>15%=有定价权。"
        "请基于以下数据给出：1)评分 2)看多/中性/看空 3)30字评语（段永平风格：简洁、直接、说人话）。"
        "数据：{data}"
    ),
    "彼得林奇": (
        "你是彼得·林奇。你的原则：PE应低于营收增速（即PE/增速<1.5），营收增速>10%，从生活中发现牛股。"
        "请基于以下数据给出：1)评分 2)看多/中性/看空 3)30字评语（林奇风格：幽默、接地气）。"
        "数据：{data}"
    ),
    "张坤": (
        "你是张坤。你的原则：高ROE(>15%)、强品牌消费龙头、低换手长期持有、PE<40不追高。"
        "请基于以下数据给出：1)评分 2)看多/中性/看空 3)30字评语（张坤风格：沉稳、重品质）。"
        "数据：{data}"
    ),
    "赵老哥": (
        "你是赵老哥，A股知名游资。你的原则：只做市值<200亿的小票、龙虎榜必须活跃、波动率要大、做短线打板。"
        "请基于以下数据给出：1)评分 2)看多/中性/看空 3)30字评语（游资风格：直接、江湖气）。"
        "数据：{data}"
    ),
    "利弗莫尔": (
        "你是杰西·利弗莫尔。你的原则：只做上升趋势、MA20>MA60、RSI在40-70、严格止损。"
        "请基于以下数据给出：1)评分 2)看多/中性/看空 3)30字评语（利弗莫尔风格：果断、趋势为王）。"
        "数据：{data}"
    ),
    "达里奥": (
        "你是瑞·达里奥。你的原则：债务周期决定一切、偏好低负债(<60%)、高股息(>1.5%)、防御性行业。"
        "请基于以下数据给出：1)评分 2)看多/中性/看空 3)30字评语（达里奥风格：宏观视角）。"
        "数据：{data}"
    ),
}


@tool
def role_play_investor(investor_name: str, stock_data: str) -> dict[str, Any]:
    """让一位知名投资人基于真实数据做出评价。

    可用的投资人：巴菲特、格雷厄姆、段永平、彼得林奇、张坤、赵老哥、利弗莫尔、达里奥。

    调用此工具后，会返回该投资人的评分(0-100)、看多/中性/看空判断、以及具有个人风格的评语。

    Args:
        investor_name: 投资人名字（必须是上面列出的名字之一）
        stock_data: 股票的关键数据摘要（PE、ROE、负债率、行业、营收增速等）
    """
    prompt = INVESTOR_PROMPTS.get(investor_name)
    if prompt is None:
        return {"error": f"未知投资人: {investor_name}，可选: {list(INVESTOR_PROMPTS.keys())}"}

    # This tool returns the prompt + data for the Agent to evaluate
    # The Agent (LLM) will role-play the investor inline
    return {
        "investor": investor_name,
        "instruction": prompt.format(data=stock_data),
        "note": "请 Agent 以该投资人的身份，基于 instruction 中的原则和 stock_data 中的数据，给出评分、判断和评语。输出格式：{score: 数字, verdict: 看多/中性/看空, comment: 30字评语}",
    }


ALL_TOOLS = [
    resolve_stock_code,
    get_etf_info,
    get_etf_holdings,
    get_etf_performance,
    get_market_data,
    get_financials,
    get_valuation,
    get_industry,
    get_capital_flow,
    get_research,
    get_lhb_data,
    role_play_investor,
]

# OpenAI function-calling format schemas
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "resolve_stock_code",
            "description": "根据股票/基金名称或代码查找 A 股 6 位代码。支持个股和场内基金。用户说名称时必须先调这个工具查代码。返回 security_type 标记是 stock 还是 fund。",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "股票/基金名称或6位代码，如'贵州茅台'、'沪深300ETF'、'510300'"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_etf_info",
            "description": "获取场内 ETF/LOF 实时行情：最新价、净值(IOPV)、折溢价率、成交额、规模(AUM)。用于分析 ETF 流动性和定价。",
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string", "description": "6位基金代码"}},
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_etf_holdings",
            "description": "获取 ETF 前十大持仓股票和行业分布。用于穿透 ETF 看底层资产质量。",
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string", "description": "6位基金代码"}},
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_etf_performance",
            "description": "获取 ETF 近1月/3月/6月/1年净值涨跌幅和年化波动率。用于评估 ETF 收益表现。",
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string", "description": "6位基金代码"}},
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_market_data",
            "description": "获取 A 股实时行情：最新价、涨跌幅、PE(TTM)、PB",
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string", "description": "6位A股代码"}},
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_financials",
            "description": "获取 A 股财务数据：ROE、净利率、毛利率、营收增速、负债率、流动比、速动比、ROIC、6年营收/利润历史、股息率",
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string", "description": "6位A股代码"}},
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_valuation",
            "description": "获取 PE/PB 当前值和 5 年历史分位（最低/最高/中位/当前处于多少%分位），用于判断估值贵不贵",
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string", "description": "6位A股代码"}},
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_industry",
            "description": "获取行业分类、生命周期、景气度增速、市值排名",
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string", "description": "6位A股代码"}},
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_capital_flow",
            "description": "获取北向资金持股比例和趋势、大宗交易、限售解禁",
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string", "description": "6位A股代码"}},
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_research",
            "description": "获取券商研报共识：覆盖券商数、共识评级、评级分布、盈利预测EPS",
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string", "description": "6位A股代码"}},
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_lhb_data",
            "description": "获取龙虎榜数据：近30日上榜次数、机构vs游资买卖金额比例。用于判断谁在主导交易。",
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string", "description": "6位A股代码"}},
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "role_play_investor",
            "description": "让一位知名投资人基于真实数据做出评分和评价。可用：巴菲特、格雷厄姆、段永平、彼得林奇、张坤、赵老哥、利弗莫尔、达里奥。至少调用 3 次，选最相关的投资人。",
            "parameters": {
                "type": "object",
                "properties": {
                    "investor_name": {
                        "type": "string",
                        "description": "投资人名字：巴菲特/格雷厄姆/段永平/彼得林奇/张坤/赵老哥/利弗莫尔/达里奥",
                    },
                    "stock_data": {
                        "type": "string",
                        "description": "股票关键数据摘要（PE、ROE、负债率、营收增速、行业等）",
                    },
                },
                "required": ["investor_name", "stock_data"],
            },
        },
    },
]

# Tool name → callable mapping
TOOL_MAP: dict[str, Any] = {
    "resolve_stock_code": resolve_stock_code,
    "get_etf_info": get_etf_info,
    "get_etf_holdings": get_etf_holdings,
    "get_etf_performance": get_etf_performance,
    "get_market_data": get_market_data,
    "get_financials": get_financials,
    "get_valuation": get_valuation,
    "get_industry": get_industry,
    "get_capital_flow": get_capital_flow,
    "get_research": get_research,
    "get_lhb_data": get_lhb_data,
    "role_play_investor": role_play_investor,
}
