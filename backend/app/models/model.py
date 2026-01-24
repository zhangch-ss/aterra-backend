from typing import Optional, Any
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, JSON
from app.models.base import BaseTable

# 模型配置表（模型卡）
class Model(BaseTable, table=True):
    user_id: Optional[str] = Field(default=None, foreign_key="user.id", index=True, description="所属用户 ID")
    name: str = Field(index=True, description="模型名称（如 gpt-4o-mini、deepseek-chat 等）")
    description: Optional[str] = Field(default=None, description="模型描述")
    provider: str = Field(max_length=50, description="模型提供方，如 'openai', 'azure', 'ollama', 'local'")
    # 使用通用 JSON 存储调用配置，支持 OpenAI 兼容格式
    invoke_config: Optional[dict[str, Any]] = Field(
        sa_column=Column(JSON),
        default=None,
        description="模型调用配置（name、parameters、client 等，JSON 格式）"
    )

    # 反向关联到 Agent（一个模型可被一个或多个 Agent 使用；此处示例为一对一）
    agent: Optional["Agent"] = Relationship(back_populates="model")
