"""UZI Agent — Streamlit Chat Frontend.

真正的多轮对话：输入 → Agent 回复 → 追问 → Agent 记得上下文继续回答。
"""

import os
import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()
API = os.getenv("API_BASE_URL", "http://127.0.0.1:8001")

st.set_page_config(page_title="财通Agent", page_icon="🤖", layout="wide")
st.title("🤖 财通Agent — 多轮对话")
st.caption("Agent 记得上下文，可以追问。例如先分析一只股票，再问具体问题。")

# ── Session state ───────────────────────────────────────────────────────────

if "messages" not in st.session_state:
    st.session_state.messages = []
if "conv_id" not in st.session_state:
    st.session_state.conv_id = None
if "thinking" not in st.session_state:
    st.session_state.thinking = []

# ── Display chat history ────────────────────────────────────────────────────

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ── Input ───────────────────────────────────────────────────────────────────

if prompt := st.chat_input("输入你的问题，例如：分析一下贵州茅台"):
    # Add user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Call Agent
    with st.chat_message("assistant"):
        with st.spinner("思考中 ..."):
            try:
                if st.session_state.conv_id is None:
                    # New conversation
                    resp = requests.post(
                        f"{API}/api/chat/start",
                        json={"message": prompt},
                        timeout=300,
                    )
                else:
                    # Continue existing conversation
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
                data = {"response": f"请求失败：{exc}"}

        # Save conversation ID
        if data.get("conversation_id"):
            st.session_state.conv_id = data["conversation_id"]

        # Show thinking in expander
        thinking = data.get("thinking", [])
        if thinking:
            with st.expander(f"调用了 {len(data.get('tools_used', []))} 个工具"):
                for step in thinking:
                    st.text(step)

        # Show response
        response_text = data.get("response", "Agent 未返回结果。")
        st.markdown(response_text)
        st.session_state.messages.append({"role": "assistant", "content": response_text})

# ── Sidebar ─────────────────────────────────────────────────────────────────

if "conv_list" not in st.session_state:
    st.session_state.conv_list = {}

with st.sidebar:
    if st.button("＋ 新对话", use_container_width=True):
        # Save current conversation to list before resetting
        if st.session_state.conv_id and st.session_state.messages:
            first_msg = st.session_state.messages[0]["content"] if st.session_state.messages else ""
            st.session_state.conv_list[st.session_state.conv_id] = first_msg[:30]
        st.session_state.messages = []
        st.session_state.conv_id = None
        st.rerun()

    # Save current conv to list
    if st.session_state.conv_id and st.session_state.messages:
        first_msg = st.session_state.messages[0]["content"] if st.session_state.messages else ""
        st.session_state.conv_list[st.session_state.conv_id] = first_msg[:30]

    if st.session_state.conv_list:
        st.divider()
        st.caption("历史对话")
        for cid, preview in list(st.session_state.conv_list.items()):
            c1, c2 = st.columns([4, 1])
            with c1:
                active = cid == st.session_state.conv_id
                label = f"{'●' if active else '○'} {preview}"
                if st.button(label, key=f"switch_{cid}", use_container_width=True):
                    if active:
                        pass  # already on this conv
                    else:
                        st.session_state.conv_id = cid
                        # Reload from server (not implemented — just switch ID)
                        st.rerun()
            with c2:
                if st.button("✕", key=f"del_{cid}"):
                    del st.session_state.conv_list[cid]
                    if st.session_state.conv_id == cid:
                        st.session_state.messages = []
                        st.session_state.conv_id = None
                    st.rerun()
    st.divider()
    st.caption("输入示例：分析茅台 / 茅台贵不贵 / 北向资金怎么看")
