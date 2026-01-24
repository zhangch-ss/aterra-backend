from typing import List, Optional
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, JSON, Index, UniqueConstraint, text
from sqlalchemy.ext.mutable import MutableDict
from app.models.link import AgentToolLink
from app.models.base import InvokeConfig, BaseTable
from enum import Enum
from datetime import datetime


class ToolTypeEnum(str, Enum):
    MCP = "MCP"
    API = "API"
    TOOL = "TOOL"


class ToolType(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: ToolTypeEnum = Field(index=True, description="工具类型（MCP / API / TOOL）")
    description: Optional[str] = Field(default=None, description="类型描述")


class Tool(BaseTable, table=True):
    """🧰 工具表"""

    user_id: Optional[str] = Field(default=None, foreign_key="user.id", index=True, description="所属用户 ID")
    name: str = Field(index=True, max_length=100, description="工具名称")
    description: Optional[str] = Field(default=None, description="工具描述")

    # 工具类型（MCP / API / TOOL）
    type: ToolTypeEnum = Field(index=True, description="工具类型")

    # 工具适用场景（可选）
    scene: Optional[str] = Field(default=None, description="适用场景")

    # 动态加载路径
    module: Optional[str] = Field(default=None, description="模块路径，例如 app.tools.math_utils")
    function: Optional[str] = Field(default=None, description="函数名，例如 calc_square")

    # 启用状态
    enabled: bool = Field(default=True, description="是否启用该工具")

    # 工具的模型调用配置
    invoke_config: Optional[InvokeConfig] = Field(
        sa_column=Column(JSON),
        description="工具调用配置（如 API endpoint, headers, params 等）"
    )

    # 预存的 Schema 与元数据（用于卡片详情直接从 DB 读取）
    tool_schema: Optional[dict] = Field(
        default=None,
        sa_column=Column(JSON),
        description="LLM 入参 Schema（来自 args_schema）"
    )
    runtime_parameters: Optional[dict] = Field(
        default=None,
        sa_column=Column(MutableDict.as_mutable(JSON)),
        description="运行时参数 Schema（通过 InjectedToolArg 解析）"
    )
    # 多对多：Agent ↔ Tool
    agents: List["Agent"] = Relationship(
        back_populates="tools",
        link_model=AgentToolLink
    )

    # ORM 级唯一约束与索引（与 Alembic 部分唯一索引保持一致）
    __table_args__ = (
        # 内置工具（user_id IS NULL）强制 (module, function) 唯一：PostgreSQL 部分唯一索引
        Index(
            "uq_tool_module_function_builtin",
            "module",
            "function",
            unique=True,
            postgresql_where=text("user_id IS NULL"),
        ),
        # 用户工具强制 (module, function, user_id) 唯一
        UniqueConstraint(
            "module",
            "function",
            "user_id",
            name="uq_tool_module_function_user",
        ),
    )
