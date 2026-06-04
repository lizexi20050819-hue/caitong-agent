"""Models for A-share Agent analysis."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── Internal model used by market_data ──────────────────────────────────────

class MarketSnapshot(BaseModel):
    input_ticker: str = ""
    resolved_ticker: str = ""
    name: str = ""
    latest_price: float | None = None
    previous_close: float | None = None
    daily_change_pct: float | None = None
    market_cap: float | None = None
    pe_ttm: float | None = None
    pb: float | None = None
    roe: float | None = None
    data_points: int = 0


# ── Agent API ───────────────────────────────────────────────────────────────

class AgentRequest(BaseModel):
    message: str = Field(..., description="用户输入，Agent 自动从中提取股票代码")


class AgentResponse(BaseModel):
    response: str
    tools_used: list[str] = Field(default_factory=list)
    thinking: list[str] = Field(default_factory=list)


class ChatRequest(BaseModel):
    conversation_id: str = Field(..., description="对话 ID，从 /api/chat/start 返回")
    message: str = Field(..., description="追问内容")


class ChatResponse(BaseModel):
    response: str
    conversation_id: str = ""
    tools_used: list[str] = Field(default_factory=list)
    thinking: list[str] = Field(default_factory=list)


class BeginChatResponse(BaseModel):
    conversation_id: str
    preview: str = ""
    status: str = "pending"


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatHistoryResponse(BaseModel):
    conversation_id: str
    preview: str = ""
    status: str = "ready"
    messages: list[ChatMessage] = Field(default_factory=list)
