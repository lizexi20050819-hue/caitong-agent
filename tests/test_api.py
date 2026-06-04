"""FastAPI route tests (no real LLM / akshare calls)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services import session_store


@pytest.fixture()
def client():
    return TestClient(app)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_chat_list_empty(client, temp_db):
    resp = client.get("/api/chat/list")
    assert resp.status_code == 200
    assert resp.json() == {"conversations": []}


def test_chat_get_not_found(client, temp_db):
    resp = client.get("/api/chat/not-exist")
    assert resp.status_code == 404


def test_chat_get_history(client, temp_db):
    session_store.save_session(
        "hist01",
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "分析宁德时代"},
            {"role": "assistant", "content": "宁德时代结论摘要"},
        ],
    )
    resp = client.get("/api/chat/hist01")
    assert resp.status_code == 200
    data = resp.json()
    assert data["conversation_id"] == "hist01"
    assert len(data["messages"]) == 2
    assert data["status"] == "ready"
    assert data["messages"][0]["role"] == "user"
    assert data["messages"][1]["content"] == "宁德时代结论摘要"


def test_chat_delete(client, temp_db):
    session_store.save_session("delme", [{"role": "user", "content": "hi"}])
    resp = client.delete("/api/chat/delme")
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True
    assert session_store.load_session("delme") is None


@patch("backend.app.main.begin_chat")
def test_chat_begin_mocked(mock_begin, client, temp_db):
    mock_begin.return_value = {
        "conversation_id": "begin01",
        "preview": "分析茅台",
        "status": "pending",
    }
    resp = client.post("/api/chat/begin", json={"message": "分析茅台"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["conversation_id"] == "begin01"
    assert body["status"] == "pending"


@patch("backend.app.main.run_chat")
def test_chat_run_mocked(mock_run, client, temp_db):
    mock_run.return_value = {
        "conversation_id": "begin01",
        "response": "测试回复",
        "thinking": [],
        "tools_used": ["get_market_data"],
        "status": "ready",
    }
    resp = client.post("/api/chat/begin01/run")
    assert resp.status_code == 200
    assert resp.json()["response"] == "测试回复"


@patch("backend.app.main.start_chat")
def test_chat_start_mocked(mock_start, client, temp_db):
    mock_start.return_value = {
        "conversation_id": "mock1234",
        "response": "测试回复",
        "thinking": ["step1"],
        "tools_used": ["get_market_data"],
    }
    resp = client.post("/api/chat/start", json={"message": "分析茅台"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["conversation_id"] == "mock1234"
    assert body["response"] == "测试回复"
    assert body["tools_used"] == ["get_market_data"]


@patch("backend.app.main.analyze")
def test_analyze_mocked(mock_analyze, client):
    mock_analyze.return_value = {
        "conclusion": "茅台估值偏高",
        "thinking": [],
        "tools_used": ["get_valuation"],
    }
    resp = client.post("/api/analyze", json={"message": "茅台贵吗"})
    assert resp.status_code == 200
    assert resp.json()["response"] == "茅台估值偏高"


@patch("backend.app.main.continue_chat")
def test_chat_continue_mocked(mock_continue, client, temp_db):
    mock_continue.return_value = {
        "conversation_id": "mock1234",
        "response": "北向资金净流入",
        "thinking": [],
        "tools_used": [],
    }
    resp = client.post(
        "/api/chat/continue",
        json={"conversation_id": "mock1234", "message": "北向呢？"},
    )
    assert resp.status_code == 200
    assert resp.json()["response"] == "北向资金净流入"
