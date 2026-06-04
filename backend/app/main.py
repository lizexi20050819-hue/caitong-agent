"""UZI Agent — A-share Analysis Agent.

支持两种模式：
  /api/analyze — 一次性完整分析
  /api/chat    — 多轮对话（有记忆）
"""

from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from typing import Annotated

from fastapi import Depends

from backend.app.models import (
    AgentRequest,
    AgentResponse,
    BeginChatResponse,
    ChatHistoryResponse,
    ChatMessage,
    ChatRequest,
    ChatResponse,
)
from backend.app.services.agent import (
    analyze,
    begin_chat,
    continue_chat,
    delete_chat,
    get_chat_history,
    list_chats,
    run_chat,
    start_chat,
)

app = FastAPI(
    title="财通Agent",
    description="A-share analysis agent with multi-turn conversation",
    version="2.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)


def get_visitor_id(request: Request, response: Response) -> str:
    """Cookie-based anonymous visitor identifier.

    Extracts `visitor_id` from the request cookie.  If missing, generates a
    new UUID4 and sets it as a persistent cookie so the same browser always
    sees its own conversation list.
    """
    visitor_id = request.cookies.get("visitor_id")
    if not visitor_id:
        visitor_id = str(uuid4())
        # Strip hyphens for a cleaner cookie value (the UUID still has enough
        # entropy — 2^122 bits — to make collisions negligible).
        visitor_id = visitor_id.replace("-", "")
        response.set_cookie(
            key="visitor_id",
            value=visitor_id,
            max_age=365 * 24 * 60 * 60,   # 1 year
            httponly=True,
            samesite="lax",
        )
    return visitor_id


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


@app.post("/api/chat/begin", response_model=BeginChatResponse)
def chat_begin(
    request: AgentRequest,
    visitor_id: Annotated[str, Depends(get_visitor_id)],
) -> BeginChatResponse:
    """创建新对话并立即落库，前端可立刻显示在历史侧栏。"""
    try:
        result = begin_chat(request.message, visitor_id)
        if result.get("error"):
            raise HTTPException(status_code=400, detail=result["error"])
        return BeginChatResponse(**result)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/chat/{conv_id}/run", response_model=ChatResponse)
def chat_run(
    conv_id: str,
    visitor_id: Annotated[str, Depends(get_visitor_id)],
) -> ChatResponse:
    """对 pending 会话执行 Agent 并返回最终回复。"""
    try:
        result = run_chat(conv_id, visitor_id)
        if result.get("error"):
            raise HTTPException(status_code=400, detail=result["error"])
        return ChatResponse(
            response=result["response"],
            conversation_id=result["conversation_id"],
            tools_used=result.get("tools_used", []),
            thinking=result.get("thinking", []),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/chat/start", response_model=ChatResponse)
def chat_start(
    request: AgentRequest,
    visitor_id: Annotated[str, Depends(get_visitor_id)],
) -> ChatResponse:
    """开始新对话（单请求：创建 + 跑 Agent）。兼容 Streamlit。"""
    try:
        result = start_chat(request.message, visitor_id)
        if result.get("error"):
            raise HTTPException(status_code=400, detail=result["error"])
        return ChatResponse(
            response=result["response"],
            conversation_id=result["conversation_id"],
            tools_used=result.get("tools_used", []),
            thinking=result.get("thinking", []),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/chat/continue", response_model=ChatResponse)
def chat_continue(
    request: ChatRequest,
    visitor_id: Annotated[str, Depends(get_visitor_id)],
) -> ChatResponse:
    """继续对话 — 传入 conversation_id 和追问内容，Agent 记得之前的所有上下文。"""
    try:
        result = continue_chat(request.conversation_id, request.message, visitor_id)
        return ChatResponse(
            response=result["response"],
            conversation_id=request.conversation_id,
            tools_used=result.get("tools_used", []),
            thinking=result.get("thinking", []),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/chat/list")
def chat_list(
    visitor_id: Annotated[str, Depends(get_visitor_id)],
):
    """列出当前访客的所有活跃对话。"""
    return {"conversations": list_chats(visitor_id)}


@app.get("/api/chat/{conv_id}", response_model=ChatHistoryResponse)
def chat_get(
    conv_id: str,
    visitor_id: Annotated[str, Depends(get_visitor_id)],
) -> ChatHistoryResponse:
    """获取对话历史（供前端刷新/重启后恢复界面）。"""
    data = get_chat_history(conv_id, visitor_id)
    if data is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    return ChatHistoryResponse(
        conversation_id=data["conversation_id"],
        preview=data.get("preview", ""),
        status=data.get("status", "ready"),
        messages=[ChatMessage(**m) for m in data["messages"]],
    )


@app.delete("/api/chat/{conv_id}")
def chat_delete(
    conv_id: str,
    visitor_id: Annotated[str, Depends(get_visitor_id)],
):
    """删除指定对话（仅限当前访客拥有的对话）。"""
    ok = delete_chat(conv_id, visitor_id)
    return {"deleted": ok, "conversation_id": conv_id}
