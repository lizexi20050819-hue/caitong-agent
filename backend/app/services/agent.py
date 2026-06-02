"""Agent — OpenAI function calling, full conversation memory.

Supports:
  - analyze: one-shot full analysis
  - chat: multi-turn conversation, agent remembers context
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import httpx

from backend.app.services.llm import load_config
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

## 关键规则
- 数字必须来自工具结果，没有就说"暂无该数据"
- 投资人评审必须基于真实数据
- 敢于表态，不能模棱两可
- 综合评分 0-100

> 不构成投资建议
"""

# In-memory conversation store: {conversation_id: [messages]}
_sessions: dict[str, list[dict]] = {}


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

    if msg.get("content"):
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


def start_chat(user_message: str) -> dict[str, Any]:
    """开始新的对话。返回 conversation_id。"""
    conv_id = str(uuid.uuid4())[:8]
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]
    _sessions[conv_id] = messages

    thinking: list[str] = []
    tools_used: list[str] = []

    for _ in range(6):
        response = _call_llm(messages, TOOL_SCHEMAS)
        new_thinking, new_tools = _execute_tools(response, messages)
        thinking.extend(new_thinking)
        tools_used.extend(new_tools)

        if not response["choices"][0]["message"].get("tool_calls"):
            return {
                "conversation_id": conv_id,
                "response": response["choices"][0]["message"]["content"] or "",
                "thinking": thinking,
                "tools_used": tools_used,
            }

    messages.append({"role": "user", "content": "请给出最终分析结论。"})
    final = _call_llm(messages)
    return {
        "conversation_id": conv_id,
        "response": final["choices"][0]["message"].get("content", ""),
        "thinking": thinking,
        "tools_used": tools_used,
    }


def continue_chat(conv_id: str, user_message: str) -> dict[str, Any]:
    """继续已有对话。Agent 记得之前的上下文和工具调用结果。"""
    messages = _sessions.get(conv_id)
    if messages is None:
        return {"error": "对话已过期，请重新开始", "conversation_id": None}

    messages.append({"role": "user", "content": user_message})

    thinking: list[str] = []
    tools_used: list[str] = []

    for _ in range(4):
        response = _call_llm(messages, TOOL_SCHEMAS)
        new_thinking, new_tools = _execute_tools(response, messages)
        thinking.extend(new_thinking)
        tools_used.extend(new_tools)

        if not response["choices"][0]["message"].get("tool_calls"):
            return {
                "conversation_id": conv_id,
                "response": response["choices"][0]["message"]["content"] or "",
                "thinking": thinking,
                "tools_used": tools_used,
            }

    final = _call_llm(messages)
    return {
        "conversation_id": conv_id,
        "response": final["choices"][0]["message"].get("content", ""),
        "thinking": thinking,
        "tools_used": tools_used,
    }


def list_chats() -> list[dict]:
    """List all active conversations with preview."""
    result = []
    for cid, msgs in _sessions.items():
        preview = ""
        for m in msgs:
            if m["role"] == "user":
                preview = m["content"][:50]
                break
        result.append({"conversation_id": cid, "preview": preview})
    return result


def delete_chat(conv_id: str) -> bool:
    """Delete a conversation."""
    if conv_id in _sessions:
        del _sessions[conv_id]
        return True
    return False
