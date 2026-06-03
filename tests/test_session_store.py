"""Tests for SQLite session store."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from backend.app.services import session_store


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db = tmp_path / "test_sessions.db"
    monkeypatch.setenv("SESSION_DB_PATH", str(db))
    session_store.init_db()
    yield db
    # Windows: SQLite 文件锁由 pytest 临时目录回收即可，勿手动 unlink


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


def test_list_sessions_preview(temp_db):
    session_store.save_session("c1", [{"role": "user", "content": "第一句"}])
    session_store.save_session("c2", [{"role": "user", "content": "第二句很长" * 5}])
    rows = session_store.list_sessions()
    ids = {r["conversation_id"] for r in rows}
    assert ids == {"c1", "c2"}
    by_id = {r["conversation_id"]: r["preview"] for r in rows}
    assert by_id["c1"] == "第一句"
    assert len(by_id["c2"]) <= 50
