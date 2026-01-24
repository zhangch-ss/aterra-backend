from datetime import datetime
from typing import List, Optional
from sqlmodel import Field, Relationship, Column, JSON
from app.models.base_uuid_model import BaseUUIDModel
import uuid

class ChatSession(BaseUUIDModel, table=True):
    __tablename__ = "chat_sessions"

    user_id: str = Field(index=True, description="所属用户ID")
    title: str = Field(default="未命名会话", description="会话标题")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow, description="更新时间")

    messages: List["ChatMessage"] = Relationship(
        back_populates="session",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )

class ChatMessage(BaseUUIDModel, table=True):
    __tablename__ = "chat_messages"

    session_id: uuid.UUID = Field(
        foreign_key="chat_sessions.id",
        index=True,
        description="所属会话ID"
    )
    role: str = Field(description="消息角色（user/assistant/tool）")
    content: str = Field(description="消息内容")
    
    # 工具调用相关字段
    tool_calls: Optional[dict] = Field(
        default=None,
        sa_column=Column(JSON),
        description="工具调用信息（仅assistant角色使用，包含name/arguments/id等）"
    )
    tool_call_id: Optional[str] = Field(
        default=None,
        description="工具调用ID（仅tool角色使用，用于关联assistant的工具调用）"
    )
    tool_name: Optional[str] = Field(
        default=None,
        description="工具名称（仅tool角色使用）"
    )
    
    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow, description="更新时间")

    session: Optional[ChatSession] = Relationship(back_populates="messages")
