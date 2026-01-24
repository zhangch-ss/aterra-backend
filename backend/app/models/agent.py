from typing import List, Optional
from sqlmodel import SQLModel, Field, Relationship
from app.models.model import Model
from app.models.tool import Tool
from app.models.knowledge import Knowledge
from app.models.link import AgentToolLink, AgentKnowledgeLink
from app.models.base import InvokeConfig, BaseTable
from sqlalchemy import Column, JSON


# 智能体表
class Agent(BaseTable, table=True):
    user_id: Optional[str] = Field(default=None, foreign_key="user.id", index=True, description="所属用户 ID")
    name: str = Field(index=True, max_length=100, description="智能体名称")
    description: Optional[str] = Field(default=None, description="智能体描述")

    type: str = Field(index=True, description="智能体类型")
    scene: str = Field(index=True, description="应用场景")

    invoke_config: Optional[InvokeConfig] = Field(
        default=None,
        sa_column=Column(JSON),
        description="智能体的模型调用配置（name / description / parameters 等）"
    )

    # 外键引用 Model 表
    model_id: str | None = Field(default=None, foreign_key="model.id", description="模型外键")

    parent_agent_id: str | None = Field(default=None, foreign_key="agent.id", index=True, description="父智能体 ID")

    # 通过 Relationship 关联 Model 配置
    model: Optional[Model] = Relationship(back_populates="agent")
    system_prompt: str | None = Field(default=None, description="系统提示")
    tools: List[Tool] = Relationship(
        back_populates="agents",
        link_model=AgentToolLink
    )
    knowledges: List[Knowledge] = Relationship(
        back_populates="agents",
        link_model=AgentKnowledgeLink
    )
    subagents: List["Agent"] = Relationship(back_populates="parent_agent")
    parent_agent: Optional["Agent"] = Relationship(
        back_populates="subagents",
        sa_relationship_kwargs={"remote_side": "Agent.id"}  # 👈 关键在这里
    )
