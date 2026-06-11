#!/usr/bin/env python3
"""Benchmark context compaction: measure token/char savings with concrete percentages.

Usage:
    python scripts/benchmark_context_compaction.py

Requires: tiktoken (pip install tiktoken)
"""

from __future__ import annotations

import copy
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

# project root on sys.path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.app.services.agent import (  # noqa: E402
    MAX_TOOL_ROUNDS_KEPT,
    SUMMARY_MAX_CHARS,
    SYSTEM_PROMPT,
    _compact_context,
)

try:
    import tiktoken

    _ENCODING = tiktoken.get_encoding("cl100k_base")
    _TOKENIZER = "tiktoken/cl100k_base"
except ImportError:
    tiktoken = None  # type: ignore[assignment]
    _ENCODING = None
    _TOKENIZER = "builtin_estimate (pip install tiktoken for exact cl100k_base)"


# ── realistic sample payloads (sizes mirror production caps) ─────────────────

_FINANCIALS_SAMPLE: dict[str, Any] = {
    "代码": "600519",
    "名称": "贵州茅台",
    "ROE(%)": 36.18,
    "净利率(%)": 52.3,
    "毛利率(%)": 91.2,
    "营收增速(%)": 15.7,
    "净利润增速(%)": 18.2,
    "资产负债率(%)": 19.4,
    "流动比率": 4.82,
    "速动比率": 3.91,
    "ROIC(%)": 28.6,
    "股息率(%)": 1.42,
    "营收历史": [
        {"年份": y, "营收(亿)": round(800 + i * 95 + (i % 3) * 12, 1), "净利润(亿)": round(400 + i * 48, 1)}
        for i, y in enumerate(range(2018, 2025))
    ],
    "备注": "数据来自公开财报，仅供投研辅助。",
}

_VALUATION_SAMPLE: dict[str, Any] = {
    "代码": "600519",
    "PE_TTM": 28.6,
    "PB": 8.42,
    "PE分位(5年%)": 42.3,
    "PB分位(5年%)": 38.7,
    "PE历史": {"最低": 22.1, "最高": 65.8, "中位": 35.2, "当前": 28.6},
    "PB历史": {"最低": 6.1, "最高": 14.2, "中位": 9.5, "当前": 8.42},
}

_MARKET_SAMPLE: dict[str, Any] = {
    "代码": "600519",
    "名称": "贵州茅台",
    "最新价": 1688.0,
    "涨跌幅(%)": 1.23,
    "成交额(亿)": 42.6,
    "换手率(%)": 0.18,
    "PE_TTM": 28.6,
    "PB": 8.42,
    "总市值(亿)": 21200,
}

_TOOL_PROFILES: list[tuple[str, dict[str, Any], int]] = [
    ("resolve_stock_code", {"matched": {"code": "600519", "name": "贵州茅台", "security_type": "stock"}}, 400),
    ("get_market_data", _MARKET_SAMPLE, 600),
    ("get_financials", _FINANCIALS_SAMPLE, 1800),
    ("get_valuation", _VALUATION_SAMPLE, 900),
    ("get_capital_flow", {
        "代码": "600519",
        "北向持股(%)": 6.55,
        "近5日北向净买入(亿)": 2.34,
        "大宗交易": [{"日期": "2025-06-01", "成交额(万)": 3200, "折溢价(%)": -1.2}],
        "限售解禁": [],
    }, 1200),
    ("get_research", {
        "代码": "600519",
        "覆盖券商数": 38,
        "rating_summary": {"buy": 22, "overweight": 10, "hold": 5, "underweight": 1, "sell": 0, "consensus": "买入"},
        "EPS预测": [{"年份": 2025, "EPS": 72.5}, {"年份": 2026, "EPS": 81.2}],
    }, 1100),
    ("get_lhb_data", {
        "代码": "600519",
        "近30日上榜次数": 2,
        "机构买入占比(%)": 35.2,
        "游资买入占比(%)": 64.8,
    }, 700),
    ("role_play_investor", {
        "投资人": "巴菲特",
        "评分": 78,
        "观点": "强品牌、高ROE，但估值不便宜，需长期视角。",
    }, 500),
]

_MOCK_SUMMARY = (
    "此前已获取贵州茅台核心数据：PE约28.6倍、PB约8.4、ROE超36%、"
    "北向持股约6.55%、研报共识偏买入。估值处于近5年中等偏低分位，"
    "财务质量优秀，营收与利润保持双位数增长，资金面北向近期净流入。"
)


def _pad_json(payload: dict[str, Any], target_chars: int) -> str:
    """Serialize and pad to approximate real tool result size (max 2000 in agent)."""
    text = json.dumps(payload, ensure_ascii=False, default=str)
    if len(text) >= target_chars:
        return text[:2000] + ("...(truncated)" if len(text) > 2000 else "")
    filler = "x" * (target_chars - len(text) - 20)
    payload = {**payload, "_padding": filler}
    text = json.dumps(payload, ensure_ascii=False, default=str)
    return text[:2000] + ("...(truncated)" if len(text) > 2000 else "")


def _make_tool_round(
    round_num: int,
    tools: list[tuple[str, int]] | None = None,
    reasoning: str | None = None,
) -> list[dict[str, Any]]:
    """One assistant tool_calls round + tool results (mirrors _execute_tools output)."""
    if tools is None:
        # default: 2 tools per round, rotate profiles
        base = (round_num - 1) * 2
        tools = [
            (_TOOL_PROFILES[base % len(_TOOL_PROFILES)][0], _TOOL_PROFILES[base % len(_TOOL_PROFILES)][2]),
            (_TOOL_PROFILES[(base + 1) % len(_TOOL_PROFILES)][0], _TOOL_PROFILES[(base + 1) % len(_TOOL_PROFILES)][2]),
        ]

    tool_calls = []
    tool_messages = []
    for i, (name, size) in enumerate(tools):
        tc_id = f"tc_r{round_num}_{i}"
        profile = next(p for p in _TOOL_PROFILES if p[0] == name)
        tool_calls.append({
            "id": tc_id,
            "type": "function",
            "function": {"name": name, "arguments": json.dumps({"ticker": "600519", "code": "600519", "name": "贵州茅台"})},
        })
        tool_messages.append({
            "role": "tool",
            "tool_call_id": tc_id,
            "content": _pad_json(profile[1], size),
        })

    assistant = {
        "role": "assistant",
        "content": reasoning or f"第{round_num}轮：调取 {', '.join(t[0] for t in tools)} 获取数据。",
        "tool_calls": tool_calls,
    }
    return [assistant, *tool_messages]


def _make_conclusion(text: str) -> dict[str, str]:
    return {"role": "assistant", "content": text}


def build_scenario_first_analysis_plus_followups(followup_rounds: int) -> list[dict[str, Any]]:
    """Simulate: 1st full analysis (4 heavy tool rounds) + N follow-up Q&A rounds."""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "全面分析一下贵州茅台，值不值得买？"},
    ]
    # first analysis: 4 tool rounds (typical full report)
    heavy_round_tools = [
        [("resolve_stock_code", 400), ("get_market_data", 600)],
        [("get_financials", 1800), ("get_valuation", 900)],
        [("get_capital_flow", 1200), ("get_research", 1100)],
        [("get_lhb_data", 700), ("role_play_investor", 500), ("role_play_investor", 500)],
    ]
    for i, tools in enumerate(heavy_round_tools, 1):
        messages.extend(_make_tool_round(i, tools=tools))
    messages.append(_make_conclusion(
        "### 综合评分\n**78/100** — 中性偏多\n\n茅台财务质量顶尖，估值不算便宜但仍在合理区间……"
    ))

    followup_specs = [
        ("北向资金最近怎么样？", [("get_capital_flow", 1200)]),
        ("和五粮液比估值呢？", [("resolve_stock_code", 400), ("get_valuation", 900), ("get_valuation", 900)]),
        ("巴菲特会怎么看？", [("role_play_investor", 500)]),
        ("龙虎榜有机构吗？", [("get_lhb_data", 700)]),
        ("股息率多少？", [("get_financials", 1800)]),
    ]
    for i in range(followup_rounds):
        q, tools = followup_specs[i % len(followup_specs)]
        messages.append({"role": "user", "content": q})
        messages.extend(_make_tool_round(4 + i + 1, tools=tools))
        messages.append(_make_conclusion(f"针对「{q}」的简要回答……"))

    return messages


def build_scenario_uniform_rounds(n_tool_rounds: int, tools_per_round: int = 2) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "分析贵州茅台"},
    ]
    for r in range(1, n_tool_rounds + 1):
        base = (r - 1) * tools_per_round
        tools = [
            (_TOOL_PROFILES[(base + j) % len(_TOOL_PROFILES)][0], _TOOL_PROFILES[(base + j) % len(_TOOL_PROFILES)][2])
            for j in range(tools_per_round)
        ]
        messages.extend(_make_tool_round(r, tools=tools))
        if r < n_tool_rounds:
            messages.append(_make_conclusion(f"第{r}轮中间结论……"))
            messages.append({"role": "user", "content": f"追问第{r}个问题"})
    return messages


def count_chars(messages: list[dict[str, Any]]) -> int:
    return len(json.dumps(messages, ensure_ascii=False, default=str))


def _estimate_text_tokens(text: str) -> int:
    """Approximate cl100k_base without tiktoken (CN-heavy JSON tool payloads)."""
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return max(1, int(cjk * 0.62 + other * 0.28))


def count_tokens(messages: list[dict[str, Any]]) -> int:
    if _ENCODING is not None:
        total = 0
        for msg in messages:
            total += 4
            for key, value in msg.items():
                if value is None:
                    continue
                if key == "tool_calls":
                    total += len(_ENCODING.encode(json.dumps(value, ensure_ascii=False)))
                else:
                    total += len(_ENCODING.encode(str(value)))
        total += 2
        return total

    total = 0
    for msg in messages:
        total += 4
        for key, value in msg.items():
            if value is None:
                continue
            if key == "tool_calls":
                total += _estimate_text_tokens(json.dumps(value, ensure_ascii=False))
            else:
                total += _estimate_text_tokens(str(value))
    total += 2
    return total


def _tool_round_starts(messages: list[dict[str, Any]]) -> list[int]:
    return [
        i for i, m in enumerate(messages)
        if m.get("role") == "assistant" and m.get("tool_calls")
    ]


def _old_section(messages: list[dict[str, Any]], max_tool_rounds: int = MAX_TOOL_ROUNDS_KEPT) -> list[dict[str, Any]]:
    starts = _tool_round_starts(messages)
    if len(starts) <= max_tool_rounds:
        return []
    cut_idx = starts[-max_tool_rounds]
    system_msg = messages[0] if messages and messages[0].get("role") == "system" else None
    return messages[1:cut_idx] if system_msg else messages[:cut_idx]


@dataclass
class BenchmarkResult:
    name: str
    tool_rounds: int
    compacted: bool
    chars_before: int
    chars_after: int
    tokens_before: int
    tokens_after: int
    old_section_chars: int
    old_section_tokens: int
    summary_chars: int
    summary_tokens: int

    @property
    def overall_saved_pct(self) -> float:
        if self.tokens_before == 0:
            return 0.0
        return (self.tokens_before - self.tokens_after) / self.tokens_before * 100

    @property
    def old_section_saved_pct(self) -> float:
        if self.old_section_tokens == 0:
            return 0.0
        return (self.old_section_tokens - self.summary_tokens) / self.old_section_tokens * 100

    @property
    def char_saved_pct(self) -> float:
        if self.chars_before == 0:
            return 0.0
        return (self.chars_before - self.chars_after) / self.chars_before * 100


def run_benchmark(
    name: str,
    messages: list[dict[str, Any]],
    *,
    max_tool_rounds: int = MAX_TOOL_ROUNDS_KEPT,
) -> BenchmarkResult:
    before = copy.deepcopy(messages)
    old_sec = _old_section(before, max_tool_rounds)
    mock = {"choices": [{"message": {"content": _MOCK_SUMMARY}}]}

    with patch("backend.app.services.agent._call_llm", return_value=mock):
        after, compacted = _compact_context(copy.deepcopy(messages), max_tool_rounds=max_tool_rounds)

    summary_msgs = []
    if compacted:
        # rebuilt: system? + summary user + ack + recent
        idx = 1 if after and after[0].get("role") == "system" else 0
        summary_msgs = after[idx:idx + 2]

    return BenchmarkResult(
        name=name,
        tool_rounds=len(_tool_round_starts(before)),
        compacted=compacted,
        chars_before=count_chars(before),
        chars_after=count_chars(after),
        tokens_before=count_tokens(before),
        tokens_after=count_tokens(after),
        old_section_chars=count_chars(old_sec) if old_sec else 0,
        old_section_tokens=count_tokens(old_sec) if old_sec else 0,
        summary_chars=count_chars(summary_msgs) if summary_msgs else 0,
        summary_tokens=count_tokens(summary_msgs) if summary_msgs else 0,
    )


def _print_row(r: BenchmarkResult) -> None:
    status = "已压缩" if r.compacted else "未触发"
    print(f"\n{'─' * 72}")
    print(f"场景: {r.name}")
    print(f"工具轮次: {r.tool_rounds}  |  状态: {status}")
    print(f"分词器: {_TOKENIZER}")
    print(f"  全量上下文  {r.tokens_before:>6} → {r.tokens_after:>6} tokens  "
          f"节省 {r.tokens_before - r.tokens_after:>5}  ({r.overall_saved_pct:.1f}%)")
    print(f"  全量字符    {r.chars_before:>6} → {r.chars_after:>6} chars   "
          f"节省 {r.chars_before - r.chars_after:>5}  ({r.char_saved_pct:.1f}%)")
    if r.compacted:
        print(f"  被压缩片段  {r.old_section_tokens:>6} → {r.summary_tokens:>6} tokens  "
              f"节省 {r.old_section_tokens - r.summary_tokens:>5}  ({r.old_section_saved_pct:.1f}%)")
        print(f"  摘要长度    {r.summary_chars} chars / {r.summary_tokens} tokens")


def main() -> int:
    if tiktoken is None:
        print("提示: 未安装 tiktoken，使用内置估算器。精确计数: pip install tiktoken\n")

    scenarios = [
        ("阈值内-5轮不压缩", build_scenario_uniform_rounds(5)),
        ("轻度-6轮压缩1轮", build_scenario_uniform_rounds(6)),
        ("中度-7轮压缩2轮", build_scenario_uniform_rounds(7)),
        ("重度-10轮压缩5轮", build_scenario_uniform_rounds(10)),
        ("首诊4轮+追问1轮(共5轮)", build_scenario_first_analysis_plus_followups(1)),
        ("首诊4轮+追问3轮(共7轮)", build_scenario_first_analysis_plus_followups(3)),
        ("首诊4轮+追问5轮(共9轮)", build_scenario_first_analysis_plus_followups(5)),
        ("首诊4轮+每轮3工具+追问2", build_scenario_uniform_rounds(6, tools_per_round=3)),
    ]

    results = [run_benchmark(name, msgs) for name, msgs in scenarios]

    print("=" * 72)
    print("上下文压缩 Token 基准测试")
    print("=" * 72)
    print("说明:")
    print("  - 模拟真实 tool 返回体积（单条最高 2000 字符，与 agent._execute_tools 一致）")
    print(f"  - 保留最近 {MAX_TOOL_ROUNDS_KEPT} 轮完整 tool 结果，更早轮次替换为 ~{SUMMARY_MAX_CHARS} 字 LLM 摘要（本测试用固定摘要）")
    print("  - 「全量上下文」= 送入 LLM 的完整 messages 数组")

    for r in results:
        _print_row(r)

    compacted = [r for r in results if r.compacted]
    if compacted:
        avg_overall = sum(r.overall_saved_pct for r in compacted) / len(compacted)
        avg_section = sum(r.old_section_saved_pct for r in compacted) / len(compacted)
        print(f"\n{'=' * 72}")
        print(f"触发压缩的 {len(compacted)} 个场景平均:")
        print(f"  全量上下文 token 节省: {avg_overall:.1f}%")
        print(f"  被压缩片段 token 节省: {avg_section:.1f}%")
        print("=" * 72)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
