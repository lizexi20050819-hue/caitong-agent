"""Tests for LLM config loader."""

from __future__ import annotations

from backend.app.services import llm


def test_load_config_deepseek(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")
    cfg = llm.load_config()
    assert cfg is not None
    assert cfg["api_key"] == "sk-test"
    assert cfg["model"] == "deepseek-chat"
    assert "deepseek" in cfg["base_url"]


def test_load_config_missing_key_returns_none(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    assert llm.load_config() is None


def test_load_config_openai(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    cfg = llm.load_config()
    assert cfg is not None
    assert cfg["api_key"] == "sk-openai"
    assert cfg["model"] == "gpt-4o-mini"
