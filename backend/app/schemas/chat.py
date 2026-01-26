from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel
from uuid import UUID


# ============ Message ============
class MessageBase(BaseModel):
    role: str
    content: str
    tool_calls: Optional[dict] = None  # 工具调用信息
    tool_call_id: Optional[str] = None  # 工具调用ID
    tool_name: Optional[str] = None  # 工具名称


class MessageCreate(MessageBase):
    pass


class SummarizeRequest(BaseModel):
    query: str
    agent_id: str
    session_id: str


class MessageUpdate(BaseModel):
    """消息更新时可修改的字段"""
    content: Optional[str] = None


class MessageOut(MessageBase):
    id: UUID
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ============ Session ============
class SessionCreate(BaseModel):
    title: Optional[str] = None


class SessionUpdate(BaseModel):
    """会话更新时可修改的字段"""
    title: Optional[str] = None


class SessionRename(BaseModel):
    title: str


class SessionOut(BaseModel):
    id: UUID
    user_id: str
    title: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SessionDetailOut(SessionOut):
    messages: List[MessageOut] = []


class ChatSessionListItem(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    user_id: Optional[str] = None
    last_message_preview: Optional[str] = None
    message_count: Optional[int] = None

    class Config:
        from_attributes = True


class SessionsListResponse(BaseModel):
    sessions: List[ChatSessionListItem]
    total: Optional[int] = None
    page: Optional[int] = None
    page_size: Optional[int] = None
