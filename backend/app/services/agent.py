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

SYSTEM_PROMPT = """你是 A 股投研 Agent。目标：理解用户意图，用**最少必要**的工具获取数据，给出有观点的结论。

## 工作方式（Agent 思维）

每轮回答前先在心里明确：
1. **用户真正要什么**（完整分析 / 单点追问 / 对比 / 是否值得买）
2. **最少需要哪些数据**——只调与问题直接相关的工具，禁止无脑全量拉取
3. **是否需要投资人视角**——仅当用户要完整首诊、或明确问「投资人怎么看/多方观点」时，才调用 `role_play_investor`（1-3 位即可，按问题选维度）
4. **何时可以不调工具**——追问且上下文已有数据时，直接基于历史 tool 结果回答

## 确定标的

用户可能说名称（如「茅台」「沪深300ETF」）或代码。你必须：
1. 先调用 `resolve_stock_code` 查找代码
2. 看 `security_type`：`stock` 用个股工具；`fund` 用 ETF/基金工具
3. 禁止自己猜代码

## 工具选用原则（示例，非固定流程）

| 用户意图 | 优先工具（按需，不必全调） |
|---------|---------------------------|
| 估值贵不贵 | resolve → 估值/行情相关 |
| 北向/资金 | resolve → 资金类 |
| 财务质量 | resolve → 财务相关 |
| 完整分析某股 | resolve → 2-4 个关键维度 + 可选投资人 |
| ETF 值得买吗 | resolve → etf_info/holdings/performance + 按需穿透 |
| 追问上一题 | **优先用已有 tool 结果**，缺什么再补调 |

调工具前用一两句话说明**为什么调这个工具**（会展示在用户界面的推理步骤中）。

## 对话模式

- **首轮完整分析**：给出综合评分 + 分章节结论；章节随问题展开，不必套固定模板
- **追问**：只答所问，不重复整份报告；无新评分时可省略综合评分段
- **换标的或缺数据**：重新 resolve，再按需调工具

## 输出格式（完整分析时遵守）

- 第一块先写综合评分：`### 综合评分\n**XX/100** — 看多/中性/看空（一句话理由）`
- 然后 `---` 和正文（核心数据、估值、资金、投资人观点等——**有什么写什么**）
- 追问轮若无新评分，可省略综合评分段

## 无关问题（必须遵守）

- 仅回答 **A 股个股、场内 ETF/基金** 投研问题
- 天气、编程、闲聊、写诗等：**礼貌拒答**，说明职责边界
- 无关问题 **禁止调用任何工具**，禁止编造数据

## 关键规则

- 数字必须来自工具结果，没有就说「暂无该数据」
- 投资人评审必须基于真实数据
- 敢于表态，综合评分 0-100

> 不构成投资建议
"""

_PLAN_INSTRUCTION = """请仅针对用户最新问题，输出简洁分析计划（3-5 条，每条一行）：
1. 用户意图是什么
2. 最小必要工具（禁止无脑全量拉取；按问题选 1-3 个关键维度即可）
3. 是否需要 role_play_investor（仅完整首诊或用户明确问投资人/多方观点时）
4. 预期输出要点
不要调用工具，不要写最终结论。"""

_VERIFY_INSTRUCTION = """你是审查员。请审视上面的分析草稿，逐项检查后输出修正版最终结论：

1. **数据支撑**：每个关键数字是否有工具返回的原始数据作为依据？无依据的数字要删除或标注"暂无数据"
2. **内部一致**：不同数据源之间有无矛盾？（如 PE 很低但 ROE 也很低 → 可能是价值陷阱，要在结论中提醒）
3. **评分合理**：综合评分是否考虑了正反两面？评分依据是否在正文中有体现？
4. **覆盖完整**：用户问的所有点都覆盖了吗？遗漏的要补充
5. **敢表态**：不要和稀泥。评分 0-100，看多/中性/看空要给出明确立场和理由

如果发现严重数据缺失（用户问的关键维度没有工具数据覆盖），在结论中诚实说明缺了什么。
如果草稿基本正确但有瑕疵，直接修正后输出完整版。

不要输出审查过程，只输出修正后的最终结论（Markdown）。"""

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
    """会话中是否已执行过工具调用（即有股票数据上下文）。"""
    for msg in messages:
        if msg.get("role") == "tool":
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


def _needs_plan(messages: list[dict[str, Any]]) -> bool:
    """Short follow-ups with prior tool context skip the extra planning LLM call."""
    user_msg = _latest_user_message(messages)
    if not user_msg:
        return False
    if _session_has_stock_context(messages) and len(user_msg) <= 24:
        return False
    return True


def _create_plan(messages: list[dict[str, Any]]) -> tuple[list[str], str]:
    """One-shot planning call; returns UI thinking steps and plan text for the first tool round."""
    plan_messages = messages + [{"role": "user", "content": _PLAN_INSTRUCTION}]
    response = _call_llm(plan_messages, tools=None)
    plan = (response["choices"][0]["message"].get("content") or "").strip()
    if not plan:
        return [], ""
    return [f"📋 计划\n{plan}"], plan


def _compact_context(
    messages: list[dict[str, Any]],
    max_tool_rounds: int = 3,
) -> tuple[list[dict[str, Any]], bool]:
    """将早期工具调用结果压缩为 LLM 摘要，保留最近 N 轮完整上下文。

    Returns (messages, compacted).
    """
    # 找到所有带 tool_calls 的 assistant 消息位置（每轮工具调用的起点）
    tool_round_starts = [
        i for i, m in enumerate(messages)
        if m.get("role") == "assistant" and m.get("tool_calls")
    ]

    if len(tool_round_starts) <= max_tool_rounds:
        return messages, False

    # 保留最近 max_tool_rounds 轮，压缩更早的内容
    cut_idx = tool_round_starts[-max_tool_rounds]

    system_msg = messages[0] if messages and messages[0].get("role") == "system" else None
    old_section = messages[1:cut_idx] if system_msg else messages[:cut_idx]
    recent_section = messages[cut_idx:]

    summary = _build_compaction_summary(old_section)

    rebuilt: list[dict[str, Any]] = []
    if system_msg:
        rebuilt.append(system_msg)
    rebuilt.append({
        "role": "user",
        "content": f"【上下文摘要 — 此前对话中已获取的数据】\n{summary}",
    })
    rebuilt.append({
        "role": "assistant",
        "content": "好的，我已了解此前获取的所有数据。请继续分析。",
    })
    rebuilt.extend(recent_section)

    return rebuilt, True


def _build_compaction_summary(old_messages: list[dict[str, Any]]) -> str:
    """Extract key data from old messages via lightweight LLM summarization."""
    user_questions: list[str] = []
    tool_snippets: list[str] = []

    for m in old_messages:
        if m.get("role") == "user":
            content = (m.get("content") or "").strip()
            if content and len(content) > 2:
                user_questions.append(content[:120])
        elif m.get("role") == "tool":
            content = (m.get("content") or "").strip()
            if content:
                tool_snippets.append(content[:400])

    if not tool_snippets:
        return "此前无工具数据。"

    q_text = " | ".join(user_questions[-5:])
    t_text = "\n---\n".join(tool_snippets[-8:])

    summary_prompt = (
        "请用 200 字以内总结以下数据中的关键信息，只提取核心数字和结论，禁止编造：\n\n"
        f"用户曾问：{q_text}\n\n"
        f"工具返回数据（节选）：\n{t_text}"
    )

    try:
        response = _call_llm(
            [{"role": "user", "content": summary_prompt}],
            tools=None,
        )
        summary = (response["choices"][0]["message"].get("content") or "").strip()
        return summary if summary else "此前已获取相关数据，详见后续分析。"
    except Exception:
        logger.warning("Compaction summary call failed")
        return "此前已获取相关数据（摘要生成失败）。"


def _verify_conclusion(messages: list[dict], draft: str) -> str:
    """Self-reflection pass: review data sufficiency, consistency, and scoring."""
    if not draft or not draft.strip():
        return draft
    verify_messages = list(messages) + [
        {"role": "assistant", "content": draft},
        {"role": "user", "content": _VERIFY_INSTRUCTION},
    ]
    try:
        response = _call_llm(verify_messages, tools=None)
        verified = (response["choices"][0]["message"].get("content") or "").strip()
        return verified if verified else draft
    except Exception:
        logger.warning("Verification call failed, returning draft")
        return draft


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
        thinking.append(f"💭 推理\n{msg['content']}")

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

        thinking.append(f"🔧 {name}\n{result_str[:200]}...")
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

    plan_hint = ""
    if _needs_plan(messages):
        plan_steps, plan_hint = _create_plan(messages)
        thinking.extend(plan_steps)

    for round_i in range(6):
        llm_messages = messages
        if plan_hint and round_i == 0:
            llm_messages = messages + [{
                "role": "user",
                "content": f"【按以下计划执行，勿向用户复述计划】\n{plan_hint}",
            }]
        response = _call_llm(llm_messages, TOOL_SCHEMAS)
        new_thinking, new_tools = _execute_tools(response, messages)
        thinking.extend(new_thinking)
        tools_used.extend(new_tools)

        # If LLM responded without tool calls, verify then return
        if not response["choices"][0]["message"].get("tool_calls"):
            draft = response["choices"][0]["message"]["content"] or ""
            verified = _verify_conclusion(messages, draft)
            if verified != draft:
                thinking.append("🔍 自检：已审查数据支撑、一致性、评分依据")
            return {"thinking": thinking, "conclusion": verified, "tools_used": tools_used}

    # Force conclusion
    messages.append({"role": "user", "content": "请基于以上数据给出最终分析结论。"})
    final = _call_llm(messages)
    draft = final["choices"][0]["message"].get("content", "")
    verified = _verify_conclusion(messages, draft)
    if verified != draft:
        thinking.append("🔍 自检：已审查数据支撑、一致性、评分依据")
    return {"thinking": thinking, "conclusion": verified, "tools_used": tools_used}


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

    # 多轮追问时压缩早期工具结果，控制上下文窗口
    messages, compacted = _compact_context(messages)
    if compacted:
        thinking.append("📦 上下文压缩：已将早期对话数据提炼为摘要，保留最近几轮完整结果")
        save_session(conv_id, messages, visitor_id)

    plan_hint = ""
    if _needs_plan(messages):
        plan_steps, plan_hint = _create_plan(messages)
        thinking.extend(plan_steps)

    for round_i in range(max_rounds):
        llm_messages = messages
        if plan_hint and round_i == 0:
            llm_messages = messages + [{
                "role": "user",
                "content": f"【按以下计划执行，勿向用户复述计划】\n{plan_hint}",
            }]
        response = _call_llm(llm_messages, TOOL_SCHEMAS)
        new_thinking, new_tools = _execute_tools(response, messages)
        thinking.extend(new_thinking)
        tools_used.extend(new_tools)

        if not response["choices"][0]["message"].get("tool_calls"):
            draft = response["choices"][0]["message"]["content"] or ""
            verified = _verify_conclusion(messages, draft)
            if verified != draft:
                thinking.append("🔍 自检：已审查数据支撑、一致性、评分依据")
            response["choices"][0]["message"]["content"] = verified
            _append_assistant_reply(response, messages)
            save_session(conv_id, messages, visitor_id)
            return {
                "conversation_id": conv_id,
                "response": verified,
                "thinking": thinking,
                "tools_used": tools_used,
                "status": "ready",
            }

    messages.append({"role": "user", "content": force_final_prompt})
    final = _call_llm(messages)
    draft = final["choices"][0]["message"].get("content", "")
    verified = _verify_conclusion(messages, draft)
    if verified != draft:
        thinking.append("🔍 自检：已审查数据支撑、一致性、评分依据")
    final["choices"][0]["message"]["content"] = verified
    _append_assistant_reply(final, messages)
    save_session(conv_id, messages, visitor_id)
    return {
        "conversation_id": conv_id,
        "response": verified,
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
