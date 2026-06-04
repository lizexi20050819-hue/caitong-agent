"""SQLite-backed chat session store — survives backend restarts."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

# project_root/backend/app/services/session_store.py -> parents[3]
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DB = _PROJECT_ROOT / "data" / "sessions.db"


def _db_path() -> Path:
    raw = os.getenv("SESSION_DB_PATH", "").strip()
    return Path(raw) if raw else _DEFAULT_DB


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_sessions (
                conversation_id TEXT PRIMARY KEY,
                messages_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        conn.commit()


def save_session(conversation_id: str, messages: list[dict[str, Any]]) -> None:
    init_db()
    now = time.time()
    payload = json.dumps(messages, ensure_ascii=False)
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO chat_sessions (conversation_id, messages_json, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(conversation_id) DO UPDATE SET
                messages_json = excluded.messages_json,
                updated_at = excluded.updated_at
            """,
            (conversation_id, payload, now, now),
        )
        conn.commit()


def load_session(conversation_id: str) -> list[dict[str, Any]] | None:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT messages_json FROM chat_sessions WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
    if row is None:
        return None
    return json.loads(row["messages_json"])


def delete_session(conversation_id: str) -> bool:
    init_db()
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM chat_sessions WHERE conversation_id = ?",
            (conversation_id,),
        )
        conn.commit()
        return cur.rowcount > 0


def session_status(messages: list[dict[str, Any]]) -> str:
    """pending = 已有用户提问，尚无对应 assistant 正文回复。"""
    last_user_idx = -1
    last_assistant_idx = -1
    for i, m in enumerate(messages):
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if role == "user" and content:
            last_user_idx = i
        elif role == "assistant" and content and not m.get("tool_calls"):
            last_assistant_idx = i
    if last_user_idx < 0:
        return "ready"
    if last_assistant_idx > last_user_idx:
        return "ready"
    return "pending"


def ui_messages(conversation_id: str) -> list[dict[str, str]] | None:
    """Extract user/assistant bubbles for the UI (no system/tool).

    带 tool_calls 的 assistant 消息是调工具前的过程说明，仅用于 LLM 上下文，
    不应作为聊天气泡展示（否则会与最终报告重复出现）。
    """
    raw = load_session(conversation_id)
    if raw is None:
        return None
    ui: list[dict[str, str]] = []
    for m in raw:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if role == "user" and content:
            ui.append({"role": "user", "content": content})
        elif role == "assistant" and content and not m.get("tool_calls"):
            ui.append({"role": "assistant", "content": content})
    return ui


def list_sessions() -> list[dict[str, str]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT conversation_id, messages_json, updated_at
            FROM chat_sessions
            ORDER BY updated_at DESC
            """
        ).fetchall()
    result: list[dict[str, str]] = []
    for row in rows:
        preview = ""
        status = "ready"
        try:
            msgs = json.loads(row["messages_json"])
            status = session_status(msgs)
            for m in msgs:
                if m.get("role") == "user" and m.get("content"):
                    preview = str(m["content"])[:50]
                    break
        except (json.JSONDecodeError, TypeError):
            preview = ""
        if status == "pending":
            preview = f"{preview}（生成中…）" if preview else "（生成中…）"
        result.append({
            "conversation_id": row["conversation_id"],
            "preview": preview,
            "status": status,
        })
    return result
