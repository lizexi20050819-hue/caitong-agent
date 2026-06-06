"""Agent — OpenAI function calling, full conversation memory.

Supports:
  - analyze: one-shot full analysis
  - chat: multi-turn conversation, agent remembers context
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

import httpx

from backend.app.services.llm import load_config
from backend.app.services.session_store import (
    delete_session,
    list_sessions,
    load_session,
    save_session,
    session_status,
    ui_messages,
)
from backend.app.services.tools import TOOL_MAP, TOOL_SCHEMAS

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是 A 股首席分析师。你可以调用工具获取真实数据。

## 对话模式

- **第一轮**：完整分析——拉数据、请投资人评审、给出综合结论。
- **追问轮**：只回答用户问的具体问题，不要重复完整的分析报告。
  例如用户问"北向资金呢？"→ 只回答北向动向，不要重新列出 ROE、PE、投资人评分等。
  用户问"估值贵不贵？"→ 只分析估值，不要说"之前我们已经分析过..."

## 第一步：确定股票代码

用户可能说名称（如"茅台"、"沪深300ETF"）或代码。你必须：
1. 先调用 `resolve_stock_code` 查找代码
2. 查看返回的 `security_type`：`stock`=个股（用 get_market_data 等），`fund`=基金（用 get_etf_info/get_etf_holdings/get_etf_performance）
3. 禁止自己猜代码

## 工作流程

**个股分析：**
1. 确定代码 → 拉数据（行情+财务+估值+行业+资金）→ 查研报/龙虎榜 → 投资人评审 → 结论

**ETF/基金分析：**
1. 确定代码 → 调 get_etf_info + get_etf_holdings + get_etf_performance
2. 穿透持仓看底层股票质量
3. 请 3-4 位投资人从以下维度评价（调用 role_play_investor）：
   - 持仓质量：重仓股 PE/ROE 整体水平和分散度
   - 估值水位：持仓整体 PE 分位，是否偏贵
   - 流动性/折溢价：成交是否活跃，折溢价是否有套利空间
   - 行业暴露：是否过于集中在某个行业
4. 输出结论：流动性、折溢价、持仓质量、收益表现、投资人观点

## 对话模式

如果用户追问（如"北向资金呢？""估值贵不贵？""投资人怎么说？"），
你不需要重新拉所有数据。基于之前的工具调用结果直接回答。
只有当用户换了一只股票或需要新数据时才调工具。

## 输出格式（必须遵守）
- 回复**第一行**先写综合评分，格式固定为：`### 综合评分\n**XX/100** — 看多/中性/看空（一句话理由）`
- 然后再写 `---` 和正文各章节（核心数据、估值、资金、投资人观点等）
- 追问轮若无新评分，可省略综合评分段

## 无关问题（必须遵守）
- 仅回答 **A 股个股、场内 ETF/基金** 的投研问题（行情、财务、估值、资金、研报、持仓、折溢价等）
- 若用户问天气、编程、闲聊、写诗、翻译、娱乐等与投研无关的内容：**礼貌拒绝**，说明自己的职责边界
- 无关问题时 **禁止调用任何工具**，禁止编造行情或财务数据
- 引导用户改为股票/ETF 相关问题

## 关键规则
- 数字必须来自工具结果，没有就说"暂无该数据"
- 投资人评审必须基于真实数据
- 敢于表态，不能模棱两可
- 综合评分 0-100

> 不构成投资建议
"""

_STOCK_CODE_RE = re.compile(r"\b\d{6}\b")

_INVESTMENT_HINTS = (
    "股", "etf", "基金", "行情", "估值", "财务", "pe", "pb", "roe", "北向", "龙虎榜",
    "研报", "茅台", "宁德", "沪深", "创业板", "科创板", "分析", "买入", "卖出", "持仓",
    "折价", "溢价", "涨停", "跌停", "市值", "营收", "利润", "转债", "债券", "投资者",
    "值得买", "贵不贵", "资金", "行业", "财报", "季报", "年报",
)

_OFF_TOPIC_HINTS = (
    "天气", "写诗", "笑话", "故事", "食谱", "菜谱", "怎么做菜", "python", "java",
    "编程", "代码怎么写", "你是谁", "你叫什么", "聊天", "谈恋爱", "翻译",
    "数学题", "世界杯", "足球", "游戏攻略", "电影推荐", "音乐推荐", "讲个段子",
    "写小说", "作文", "历史朝代", "明星八卦",
)

OFF_TOPIC_REPLY = (
    "我是 **A 股投研助手**，只能回答与 A 股个股、场内 ETF/基金相关的问题"
    "（行情分析、估值、财务、资金、研报、投资人视角等）。\n\n"
    "请换个与股票/ETF 相关的问题，例如：\n"
    "- 分析一下贵州茅台\n"
    "- 沪深300ETF 值得买吗"
)


def off_topic_reply(message: str, *, has_stock_context: bool = False) -> str | None:
    """明显无关则返回固定拒答文案；否则交 LLM 处理。"""
    text = (message or "").strip()
    if not text:
        return OFF_TOPIC_REPLY

    lowered = text.lower()
    if _STOCK_CODE_RE.search(text):
        return None
    if any(hint in lowered for hint in _OFF_TOPIC_HINTS):
        return OFF_TOPIC_REPLY
    if any(hint in lowered for hint in _INVESTMENT_HINTS):
        return None
    if has_stock_context and len(text) <= 24:
        return None
    return None


def _session_has_stock_context(messages: list[dict[str, Any]]) -> bool:
    for msg in messages:
        if msg.get("role") == "tool":
            return True
        content = (msg.get("content") or "")
        lowered = content.lower()
        if msg.get("role") == "user" and any(h in lowered for h in _INVESTMENT_HINTS):
            return True
        if _STOCK_CODE_RE.search(content):
            return True
    return False


def _finish_with_refusal(
    conv_id: str,
    messages: list[dict[str, Any]],
    visitor_id: str,
    reply_text: str,
) -> dict[str, Any]:
    messages.append({"role": "assistant", "content": reply_text})
    save_session(conv_id, messages, visitor_id)
    return {
        "conversation_id": conv_id,
        "response": reply_text,
        "thinking": [],
        "tools_used": [],
        "status": "ready",
    }


def _latest_user_message(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return (msg.get("content") or "").strip()
    return ""

def _append_assistant_reply(response: dict, messages: list[dict]) -> None:
    """Persist final assistant text when this turn has no tool_calls."""
    msg = response["choices"][0]["message"]
    if msg.get("tool_calls"):
        return
    messages.append({"role": "assistant", "content": msg.get("content") or ""})


def _call_llm(messages: list[dict], tools: list[dict] | None = None) -> dict:
    """Call DeepSeek/OpenAI API."""
    config = load_config()
    if config is None:
        raise RuntimeError("未配置 LLM API Key")

    url = (config.get("base_url") or "https://api.deepseek.com").rstrip("/") + "/chat/completions"
    payload: dict[str, Any] = {
        "model": config["model"], "messages": messages,
        "temperature": 0.3, "max_tokens": 2048,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    resp = httpx.Client(proxy=None, trust_env=False, timeout=120).post(
        url,
        headers={"Authorization": f"Bearer {config['api_key']}", "Content-Type": "application/json"},
        json=payload,
    )
    resp.raise_for_status()
    return resp.json()


def _execute_tools(response: dict, messages: list[dict]) -> tuple[list[str], list[str]]:
    """Execute tool calls from LLM response. Returns (thinking_steps, tool_names)."""
    thinking: list[str] = []
    tools_used: list[str] = []
    choice = response["choices"][0]
    msg = choice["message"]

    # 仅记录调工具前的中间说明；最终回复正文走 response，避免在 thinking 里重复一遍
    if msg.get("content") and msg.get("tool_calls"):
        thinking.append(msg["content"])

    if not msg.get("tool_calls"):
        return thinking, tools_used

    messages.append({
        "role": "assistant",
        "content": msg.get("content") or "",
        "tool_calls": msg["tool_calls"],
    })

    for tc in msg["tool_calls"]:
        name = tc["function"]["name"]
        args = json.loads(tc["function"]["arguments"])
        tools_used.append(name)

        fn = TOOL_MAP.get(name)
        try:
            if fn and hasattr(fn, 'invoke'):
                result = fn.invoke(args)
            elif fn:
                result = fn(**args)
            else:
                result = {"error": f"未知工具: {name}"}
            result_str = json.dumps(result, ensure_ascii=False, default=str)
        except Exception as exc:
            result_str = json.dumps({"error": str(exc)}, ensure_ascii=False)

        if len(result_str) > 2000:
            result_str = result_str[:2000] + '...(truncated)'

        thinking.append(f"调用 {name}: {result_str[:200]}...")
        messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result_str})

    return thinking, tools_used


def analyze(user_message: str) -> dict[str, Any]:
    """一次性完整分析。"""
    if refusal := off_topic_reply(user_message):
        return {"thinking": [], "conclusion": refusal, "tools_used": []}

    thinking: list[str] = []
    tools_used: list[str] = []
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    for _ in range(6):
        response = _call_llm(messages, TOOL_SCHEMAS)
        new_thinking, new_tools = _execute_tools(response, messages)
        thinking.extend(new_thinking)
        tools_used.extend(new_tools)

        # If LLM responded without tool calls, we're done
        if not response["choices"][0]["message"].get("tool_calls"):
            return {"thinking": thinking, "conclusion": response["choices"][0]["message"]["content"] or "", "tools_used": tools_used}

    # Force conclusion
    messages.append({"role": "user", "content": "请基于以上数据给出最终分析结论。"})
    final = _call_llm(messages)
    return {"thinking": thinking, "conclusion": final["choices"][0]["message"].get("content", ""), "tools_used": tools_used}


def _run_chat_loop(
    conv_id: str,
    messages: list[dict[str, Any]],
    visitor_id: str = "",
    *,
    max_rounds: int = 6,
    force_final_prompt: str = "请给出最终分析结论。",
) -> dict[str, Any]:
    """Run agent on in-memory messages; persist when a final assistant reply is ready."""
    thinking: list[str] = []
    tools_used: list[str] = []

    for _ in range(max_rounds):
        response = _call_llm(messages, TOOL_SCHEMAS)
        new_thinking, new_tools = _execute_tools(response, messages)
        thinking.extend(new_thinking)
        tools_used.extend(new_tools)

        if not response["choices"][0]["message"].get("tool_calls"):
            _append_assistant_reply(response, messages)
            save_session(conv_id, messages, visitor_id)
            return {
                "conversation_id": conv_id,
                "response": response["choices"][0]["message"]["content"] or "",
                "thinking": thinking,
                "tools_used": tools_used,
                "status": "ready",
            }

    messages.append({"role": "user", "content": force_final_prompt})
    final = _call_llm(messages)
    _append_assistant_reply(final, messages)
    save_session(conv_id, messages, visitor_id)
    return {
        "conversation_id": conv_id,
        "response": final["choices"][0]["message"].get("content", ""),
        "thinking": thinking,
        "tools_used": tools_used,
        "status": "ready",
    }


def begin_chat(user_message: str, visitor_id: str = "") -> dict[str, Any]:
    """创建新对话并立即落库（仅 system + user），供前端立刻显示在历史中。"""
    conv_id = str(uuid.uuid4())[:8]
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]
    save_session(conv_id, messages, visitor_id)
    preview = user_message[:50]
    return {
        "conversation_id": conv_id,
        "preview": preview,
        "status": "pending",
    }


def run_chat(conv_id: str, visitor_id: str = "") -> dict[str, Any]:
    """对 pending 会话执行 Agent，生成 assistant 回复。"""
    messages = load_session(conv_id, visitor_id)
    if messages is None:
        return {"error": "对话不存在", "conversation_id": conv_id}
    if session_status(messages) != "pending":
        return {"error": "当前对话不在等待回复状态", "conversation_id": conv_id}
    if refusal := off_topic_reply(_latest_user_message(messages)):
        return _finish_with_refusal(conv_id, messages, visitor_id, refusal)
    return _run_chat_loop(conv_id, messages, visitor_id, max_rounds=6)


def start_chat(user_message: str, visitor_id: str = "") -> dict[str, Any]:
    """开始新对话（一次性：创建 + 跑 Agent）。Streamlit 等单请求客户端仍可用。"""
    begun = begin_chat(user_message, visitor_id)
    if begun.get("error"):
        return begun
    result = run_chat(begun["conversation_id"], visitor_id)
    if result.get("error"):
        return result
    return result


def continue_chat(conv_id: str, user_message: str, visitor_id: str = "") -> dict[str, Any]:
    """继续已有对话。Agent 记得之前的上下文和工具调用结果。"""
    loaded = load_session(conv_id, visitor_id)
    if loaded is None:
        return {"error": "对话已过期，请重新开始", "conversation_id": None}
    messages = loaded

    messages.append({"role": "user", "content": user_message})
    save_session(conv_id, messages, visitor_id)

    if refusal := off_topic_reply(
        user_message,
        has_stock_context=_session_has_stock_context(messages),
    ):
        return _finish_with_refusal(conv_id, messages, visitor_id, refusal)

    return _run_chat_loop(
        conv_id,
        messages,
        visitor_id,
        max_rounds=4,
        force_final_prompt="请基于上下文给出回答。",
    )


def list_chats(visitor_id: str = "") -> list[dict]:
    """List all conversations for a visitor (from SQLite)."""
    return list_sessions(visitor_id)


def delete_chat(conv_id: str, visitor_id: str = "") -> bool:
    """Delete a conversation (visitor-scoped)."""
    return delete_session(conv_id, visitor_id)


def get_chat_history(conv_id: str, visitor_id: str = "") -> dict[str, Any] | None:
    """Load conversation for UI restore after page/backend restart."""
    raw = load_session(conv_id, visitor_id)
    if raw is None:
        return None
    ui = ui_messages(conv_id, visitor_id)
    if ui is None:
        return None
    preview = ""
    for m in ui:
        if m["role"] == "user":
            preview = m["content"][:50]
            break
    return {
        "conversation_id": conv_id,
        "preview": preview,
        "status": session_status(raw),
        "messages": ui,
    }
