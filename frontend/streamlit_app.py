"""UZI Agent — Streamlit Chat Frontend.

真正的多轮对话：输入 → Agent 回复 → 追问 → Agent 记得上下文继续回答。
历史对话从后端 SQLite 加载，重启前后端后仍可恢复。
"""

import os

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()
API = os.getenv("API_BASE_URL", "http://127.0.0.1:8001")

st.set_page_config(page_title="财通Agent", page_icon="🤖", layout="wide")
st.title("🤖 财通Agent — 多轮对话")
st.caption("Agent 记得上下文，可以追问。历史对话保存在后端 SQLite，重启后可从侧边栏恢复。")


def _fetch_conv_list() -> dict[str, str]:
    """Load conversation list from backend SQLite."""
    try:
        resp = requests.get(f"{API}/api/chat/list", timeout=10)
        resp.raise_for_status()
        rows = resp.json().get("conversations", [])
        return {r["conversation_id"]: r.get("preview", "") for r in rows}
    except requests.RequestException:
        return {}


def _load_conv_from_server(conv_id: str) -> bool:
    """Restore UI messages for a conversation_id."""
    try:
        resp = requests.get(f"{API}/api/chat/{conv_id}", timeout=10)
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        data = resp.json()
        st.session_state.conv_id = data["conversation_id"]
        st.session_state.messages = [
            {"role": m["role"], "content": m["content"]} for m in data.get("messages", [])
        ]
        return True
    except requests.RequestException:
        return False


# ── Session state ───────────────────────────────────────────────────────────

if "messages" not in st.session_state:
    st.session_state.messages = []
if "conv_id" not in st.session_state:
    st.session_state.conv_id = None
if "thinking" not in st.session_state:
    st.session_state.thinking = []
if "conv_list" not in st.session_state:
    st.session_state.conv_list = {}

# ── Sidebar（先处理切换/删除，再渲染主聊天区）────────────────────────────────

with st.sidebar:
    if st.button("↻ 刷新历史", use_container_width=True):
        st.session_state.conv_list = _fetch_conv_list()
        st.rerun()

    if st.button("＋ 新对话", use_container_width=True):
        st.session_state.messages = []
        st.session_state.conv_id = None
        st.rerun()

    # 首次进入页面：从 SQLite 同步历史列表
    if not st.session_state.conv_list:
        st.session_state.conv_list = _fetch_conv_list()

    if st.session_state.conv_list:
        st.divider()
        st.caption("历史对话（来自 data/sessions.db）")
        for cid, preview in list(st.session_state.conv_list.items()):
            c1, c2 = st.columns([4, 1])
            with c1:
                active = cid == st.session_state.conv_id
                label = f"{'●' if active else '○'} {preview or cid}"
                if st.button(label, key=f"switch_{cid}", use_container_width=True):
                    if not active:
                        if _load_conv_from_server(cid):
                            st.rerun()
                        else:
                            st.warning("对话不存在或后端未启动")
            with c2:
                if st.button("✕", key=f"del_{cid}"):
                    try:
                        requests.delete(f"{API}/api/chat/{cid}", timeout=10)
                    except requests.RequestException:
                        pass
                    st.session_state.conv_list.pop(cid, None)
                    if st.session_state.conv_id == cid:
                        st.session_state.messages = []
                        st.session_state.conv_id = None
                    st.rerun()

    st.divider()
    st.caption("输入示例：分析茅台 / 茅台贵不贵 / 北向资金怎么看")

# ── Display chat history ────────────────────────────────────────────────────

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ── Input ───────────────────────────────────────────────────────────────────

if prompt := st.chat_input("输入你的问题，例如：分析一下贵州茅台"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("思考中 ..."):
            try:
                if st.session_state.conv_id is None:
                    resp = requests.post(
                        f"{API}/api/chat/start",
                        json={"message": prompt},
                        timeout=300,
                    )
                else:
                    resp = requests.post(
                        f"{API}/api/chat/continue",
                        json={
                            "conversation_id": st.session_state.conv_id,
                            "message": prompt,
                        },
                        timeout=300,
                    )
                resp.raise_for_status()
                data = resp.json()
            except requests.Timeout:
                data = {"response": "分析超时，请重试。"}
            except requests.RequestException as exc:
                data = {"response": f"请求失败：{exc}（请先启动后端 run_backend.ps1）"}

        if data.get("conversation_id"):
            st.session_state.conv_id = data["conversation_id"]
            preview = st.session_state.messages[0]["content"][:30] if st.session_state.messages else ""
            st.session_state.conv_list[st.session_state.conv_id] = preview

        thinking = data.get("thinking", [])
        if thinking:
            with st.expander(f"调用了 {len(data.get('tools_used', []))} 个工具"):
                for step in thinking:
                    st.text(step)

        response_text = data.get("response", "Agent 未返回结果。")
        st.markdown(response_text)
        st.session_state.messages.append({"role": "assistant", "content": response_text})
