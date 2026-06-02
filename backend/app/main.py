"""UZI Agent — A-share Analysis Agent.

支持两种模式：
  /api/analyze — 一次性完整分析
  /api/chat    — 多轮对话（有记忆）
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.app.models import AgentRequest, AgentResponse, ChatRequest, ChatResponse
from backend.app.services.agent import analyze, start_chat, continue_chat, list_chats, delete_chat

app = FastAPI(
    title="财通Agent",
    description="A-share analysis agent with multi-turn conversation",
    version="2.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/analyze", response_model=AgentResponse)
def agent_analyze(request: AgentRequest) -> AgentResponse:
    """一次性分析 — 输入一句话，Agent 自己找代码、调工具、出报告。"""
    try:
        result = analyze(request.message)
        return AgentResponse(
            response=result["conclusion"],
            tools_used=result["tools_used"],
            thinking=result["thinking"],
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/chat/start", response_model=ChatResponse)
def chat_start(request: AgentRequest) -> ChatResponse:
    """开始新对话 — 返回 conversation_id 用于后续追问。"""
    try:
        result = start_chat(request.message)
        return ChatResponse(
            response=result["response"],
            conversation_id=result["conversation_id"],
            tools_used=result.get("tools_used", []),
            thinking=result.get("thinking", []),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/chat/continue", response_model=ChatResponse)
def chat_continue(request: ChatRequest) -> ChatResponse:
    """继续对话 — 传入 conversation_id 和追问内容，Agent 记得之前的所有上下文。"""
    try:
        result = continue_chat(request.conversation_id, request.message)
        return ChatResponse(
            response=result["response"],
            conversation_id=request.conversation_id,
            tools_used=result.get("tools_used", []),
            thinking=result.get("thinking", []),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/chat/list")
def chat_list():
    """列出所有活跃对话。"""
    return {"conversations": list_chats()}


@app.delete("/api/chat/{conv_id}")
def chat_delete(conv_id: str):
    """删除指定对话。"""
    ok = delete_chat(conv_id)
    return {"deleted": ok, "conversation_id": conv_id}
