"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from backend.app.services import session_store


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """Isolated SQLite DB for each test."""
    db = tmp_path / "test_sessions.db"
    monkeypatch.setenv("SESSION_DB_PATH", str(db))
    session_store.init_db()
    yield db
