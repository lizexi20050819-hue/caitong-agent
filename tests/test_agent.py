"""Tests for agent helpers (no LLM network)."""

from __future__ import annotations

from backend.app.services.agent import (
    _append_assistant_reply,
    _execute_tools,
    begin_chat,
    get_chat_history,
    run_chat,
)
from backend.app.services import session_store
from backend.app.services import session_store


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
                    "function": {"name": "resolve_stock_code", "arguments": '{"query":"茅台"}'},
                }],
            },
        }],
    }
    thinking, tools_used = _execute_tools(response, messages)
    assert thinking[0] == "先查代码和数据"
    assert thinking[1].startswith("调用 resolve_stock_code:")
    assert tools_used == ["resolve_stock_code"]


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
