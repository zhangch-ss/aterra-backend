from typing import List, Optional
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, JSON
from uuid import uuid4

# 多对多关联表（Agent <-> Tool）
class AgentToolLink(SQLModel, table=True):
    # 复合主键（agent_id + tool_id）
    agent_id: str = Field(default=None, foreign_key="agent.id", primary_key=True)
    tool_id: str = Field(default=None, foreign_key="tool.id", primary_key=True)

# 多对多关联表（Agent <-> Knowledge）
class AgentKnowledgeLink(SQLModel, table=True):
    # 复合主键（agent_id + knowledge_id）
    agent_id: str = Field(default=None, foreign_key="agent.id", primary_key=True)
    knowledge_id: str = Field(default=None, foreign_key="knowledge.id", primary_key=True)
