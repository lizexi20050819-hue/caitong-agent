"""Tests for SQLite session store."""

from __future__ import annotations

from backend.app.services import session_store


def test_save_load_roundtrip(temp_db):
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "分析茅台"},
        {"role": "assistant", "content": "好的"},
    ]
    session_store.save_session("abc12345", messages)
    loaded = session_store.load_session("abc12345")
    assert loaded == messages


def test_load_missing_returns_none(temp_db):
    assert session_store.load_session("missing") is None


def test_delete_session(temp_db):
    session_store.save_session("del1", [{"role": "user", "content": "hi"}])
    assert session_store.delete_session("del1") is True
    assert session_store.load_session("del1") is None
    assert session_store.delete_session("del1") is False


def test_session_status_pending_and_ready(temp_db):
    pending = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "分析茅台"},
    ]
    ready = pending + [{"role": "assistant", "content": "结论"}]
    assert session_store.session_status(pending) == "pending"
    assert session_store.session_status(ready) == "ready"


def test_list_sessions_preview(temp_db):
    session_store.save_session(
        "c1",
        [
            {"role": "user", "content": "第一句"},
            {"role": "assistant", "content": "回复"},
        ],
    )
    session_store.save_session(
        "c2",
        [
            {"role": "user", "content": "第二句很长" * 5},
            {"role": "assistant", "content": "回复"},
        ],
    )
    rows = session_store.list_sessions()
    ids = {r["conversation_id"] for r in rows}
    assert ids == {"c1", "c2"}
    by_id = {r["conversation_id"]: r["preview"] for r in rows}
    assert by_id["c1"] == "第一句"
    assert len(by_id["c2"]) <= 50


def test_list_sessions_pending_preview(temp_db):
    session_store.save_session(
        "pending1",
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "分析茅台"},
        ],
    )
    rows = session_store.list_sessions()
    row = next(r for r in rows if r["conversation_id"] == "pending1")
    assert row["status"] == "pending"
    assert row["preview"].endswith("（生成中…）")


def test_ui_messages_skips_system_and_tool(temp_db):
    session_store.save_session(
        "ui1",
        [
            {"role": "system", "content": "hidden"},
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "", "tool_calls": [{}]},
            {"role": "tool", "content": "{}"},
            {"role": "assistant", "content": "结论"},
        ],
    )
    ui = session_store.ui_messages("ui1")
    assert ui == [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "结论"},
    ]


def test_ui_messages_skips_tool_turn_preface(temp_db):
    session_store.save_session(
        "ui2",
        [
            {"role": "user", "content": "分析茅台"},
            {
                "role": "assistant",
                "content": "好的，我先查一下贵州茅台的股票代码。",
                "tool_calls": [{"id": "1", "function": {"name": "resolve_stock_code", "arguments": "{}"}}],
            },
            {"role": "tool", "content": "{}"},
            {
                "role": "assistant",
                "content": "数据齐全了，现在请几位投资人来做评审。",
                "tool_calls": [{"id": "2", "function": {"name": "role_play_investor", "arguments": "{}"}}],
            },
            {"role": "tool", "content": "{}"},
            {"role": "assistant", "content": "完整分析报告"},
        ],
    )
    ui = session_store.ui_messages("ui2")
    assert ui == [
        {"role": "user", "content": "分析茅台"},
        {"role": "assistant", "content": "完整分析报告"},
    ]
