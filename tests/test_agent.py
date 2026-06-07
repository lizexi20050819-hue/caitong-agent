"""Tests for agent helpers (no LLM network)."""

from __future__ import annotations

from unittest.mock import patch

from backend.app.services.agent import (
    OFF_TOPIC_REPLY,
    _append_assistant_reply,
    _build_compaction_summary,
    _compact_context,
    _execute_tools,
    _needs_plan,
    _verify_conclusion,
    begin_chat,
    get_chat_history,
    off_topic_reply,
    run_chat,
)
from backend.app.services import session_store


def test_off_topic_reply_blocks_weather():
    assert off_topic_reply("今天北京天气怎么样") == OFF_TOPIC_REPLY


def test_off_topic_reply_allows_stock_question():
    assert off_topic_reply("分析一下贵州茅台") is None
    assert off_topic_reply("600519 北向资金怎么看") is None


def test_off_topic_reply_allows_short_followup_in_context():
    assert off_topic_reply("北向呢？", has_stock_context=True) is None


def test_run_chat_refuses_off_topic_without_llm(temp_db):
    begun = begin_chat("讲个笑话")
    result = run_chat(begun["conversation_id"])
    assert result["response"] == OFF_TOPIC_REPLY
    assert result["tools_used"] == []
    loaded = session_store.load_session(begun["conversation_id"])
    assert loaded[-1]["role"] == "assistant"
    assert loaded[-1]["content"] == OFF_TOPIC_REPLY


def test_begin_chat_saves_pending_session(temp_db):
    result = begin_chat("分析茅台")
    assert result["status"] == "pending"
    assert result["conversation_id"]
    loaded = session_store.load_session(result["conversation_id"])
    assert loaded[-1]["role"] == "user"
    assert loaded[-1]["content"] == "分析茅台"
    assert session_store.session_status(loaded) == "pending"


def test_run_chat_rejects_when_not_pending(temp_db):
    session_store.save_session(
        "done01",
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "已回复"},
        ],
    )
    result = run_chat("done01")
    assert result["error"] == "当前对话不在等待回复状态"


def test_execute_tools_omits_final_reply_from_thinking():
    messages: list[dict] = [{"role": "user", "content": "分析茅台"}]
    response = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "# 贵州茅台分析报告\n\n完整结论",
            },
        }],
    }
    thinking, tools_used = _execute_tools(response, messages)
    assert thinking == []
    assert tools_used == []


def test_execute_tools_keeps_preface_before_tool_calls():
    messages: list[dict] = [{"role": "user", "content": "分析茅台"}]
    response = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "先查代码和数据",
                "tool_calls": [{
                    "id": "tc1",
                    "function": {"name": "resolve_stock_code", "arguments": '{"name":"茅台"}'},
                }],
            },
        }],
    }
    thinking, tools_used = _execute_tools(response, messages)
    assert thinking[0] == "💭 推理\n先查代码和数据"
    assert thinking[1].startswith("🔧 resolve_stock_code\n")
    assert tools_used == ["resolve_stock_code"]


def test_needs_plan_skips_short_followup_with_context():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "分析茅台"},
        {"role": "tool", "tool_call_id": "1", "content": "{}"},
        {"role": "assistant", "content": "结论"},
        {"role": "user", "content": "北向呢？"},
    ]
    assert _needs_plan(messages) is False


def test_needs_plan_for_new_analysis():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "分析一下宁德时代"},
    ]
    assert _needs_plan(messages) is True


def test_append_assistant_reply_skips_tool_turn():
    messages: list[dict] = [{"role": "user", "content": "hi"}]
    response = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "1", "function": {"name": "x", "arguments": "{}"}}],
            },
        }],
    }
    _append_assistant_reply(response, messages)
    assert len(messages) == 1


def test_append_assistant_reply_adds_text():
    messages: list[dict] = [{"role": "user", "content": "hi"}]
    response = {
        "choices": [{"message": {"role": "assistant", "content": "结论"}}],
    }
    _append_assistant_reply(response, messages)
    assert messages[-1] == {"role": "assistant", "content": "结论"}


def test_get_chat_history(temp_db):
    session_store.save_session(
        "agent1",
        [
            {"role": "system", "content": "hidden"},
            {"role": "user", "content": "第一个问题"},
            {"role": "assistant", "content": "第一个回答"},
        ],
    )
    hist = get_chat_history("agent1")
    assert hist is not None
    assert hist["conversation_id"] == "agent1"
    assert hist["preview"] == "第一个问题"
    assert len(hist["messages"]) == 2


def test_get_chat_history_missing(temp_db):
    assert get_chat_history("nope") is None


def test_verify_conclusion_returns_draft_when_empty():
    """空草稿或纯空白直接返回，不浪费 LLM 调用"""
    messages = [{"role": "user", "content": "分析茅台"}]
    assert _verify_conclusion(messages, "") == ""
    assert _verify_conclusion(messages, "  ") == "  "


def test_verify_conclusion_fallback_on_llm_error():
    """LLM 调用失败时降级返回原草稿"""
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "分析茅台"},
    ]
    with patch("backend.app.services.agent._call_llm", side_effect=RuntimeError("API down")):
        result = _verify_conclusion(messages, "草稿内容")
        assert result == "草稿内容"


def test_verify_conclusion_returns_verified_text():
    """正常情况返回 LLM 修正后的结论"""
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "分析茅台"},
    ]
    mock_response = {
        "choices": [{"message": {"content": "修正后的结论"}}],
    }
    with patch("backend.app.services.agent._call_llm", return_value=mock_response):
        result = _verify_conclusion(messages, "原始草稿")
        assert result == "修正后的结论"


def test_verify_conclusion_empty_llm_response_falls_back():
    """LLM 返回空内容时降级"""
    messages = [{"role": "system", "content": "sys"}]
    mock_response = {"choices": [{"message": {"content": ""}}]}
    with patch("backend.app.services.agent._call_llm", return_value=mock_response):
        result = _verify_conclusion(messages, "原始草稿")
        assert result == "原始草稿"


# ── context compaction tests ──


def _make_tool_round(round_num: int) -> list[dict]:
    """Helper: 创建一轮工具调用的消息（assistant tool_calls + tool result）。"""
    return [
        {
            "role": "assistant",
            "content": f"推理{round_num}",
            "tool_calls": [{
                "id": f"tc{round_num}",
                "function": {"name": f"tool{round_num}", "arguments": "{}"},
            }],
        },
        {
            "role": "tool",
            "tool_call_id": f"tc{round_num}",
            "content": f'{{"data{round_num}": {round_num * 100}}}',
        },
    ]


def test_compact_context_skips_when_under_threshold():
    """工具轮次不足时不触发压缩"""
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "分析茅台"},
        *_make_tool_round(1),
        {"role": "assistant", "content": "结论"},
    ]
    result, compacted = _compact_context(messages, max_tool_rounds=3)
    assert compacted is False
    assert result is messages  # 相同引用，未修改


def test_compact_context_triggers_when_over_threshold():
    """超过阈值时压缩早期轮次"""
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "分析茅台"},
        *_make_tool_round(1),
        *_make_tool_round(2),
        {"role": "assistant", "content": "第一轮结论"},
        {"role": "user", "content": "北向呢？"},
        *_make_tool_round(3),
        {"role": "assistant", "content": "北向结论"},
        {"role": "user", "content": "比亚迪呢？"},
        *_make_tool_round(4),
    ]
    mock_summary = {"choices": [{"message": {"content": "茅台PE19倍，北向6.55%"}}]}

    with patch("backend.app.services.agent._call_llm", return_value=mock_summary):
        result, compacted = _compact_context(messages, max_tool_rounds=2)

    assert compacted is True
    # 重建后应包含 system + summary user + ack assistant + 最近 2 轮
    assert result[0] == messages[0]  # system 保留
    assert "上下文摘要" in result[1]["content"]
    assert "茅台PE19倍" in result[1]["content"]
    assert result[2]["role"] == "assistant"
    # 最近 2 轮的工具调用应该还在
    tool_rounds_in_result = sum(
        1 for m in result if m.get("role") == "assistant" and m.get("tool_calls")
    )
    assert tool_rounds_in_result == 2


def test_build_compaction_summary_empty():
    """空消息返回兜底文案"""
    assert "无工具数据" in _build_compaction_summary([])


def test_compact_context_preserves_system_prompt():
    """没有 system 消息时也能正常工作"""
    messages = [
        {"role": "user", "content": "分析茅台"},
        *_make_tool_round(1),
        *_make_tool_round(2),
        *_make_tool_round(3),
        *_make_tool_round(4),
    ]
    mock_summary = {"choices": [{"message": {"content": "摘要"}}]}

    with patch("backend.app.services.agent._call_llm", return_value=mock_summary):
        result, compacted = _compact_context(messages, max_tool_rounds=2)

    assert compacted is True
    assert result[0]["role"] == "user"
    assert "上下文摘要" in result[0]["content"]
