from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship
from app.models.base import BaseTable
from app.models.link import AgentKnowledgeLink

class Knowledge(BaseTable, table=True):
    """知识库表：用于管理可供 Agent 使用的知识集合（RAG 索引、文档集合等）。"""
    user_id: Optional[str] = Field(default=None, foreign_key="user.id", index=True, description="所属用户 ID")
    name: str = Field(index=True, max_length=100, description="知识库名称")
    description: Optional[str] = Field(default=None, description="知识库描述")
    # 可扩展字段：source/type/index_name 等

    # 反向关联到 Agent（多对多）
    agents: List["Agent"] = Relationship(back_populates="knowledges", link_model=AgentKnowledgeLink)
