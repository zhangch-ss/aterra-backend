# app/models/base_mixins.py
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field
from uuid import uuid4
from sqlalchemy import Column, JSON


# ====================================================
# ① ID + 时间戳 + 激活状态
# ====================================================
class IDTimestampMixin(SQLModel):
    """提供主键、时间戳、逻辑删除字段"""
    id: str = Field(
        default_factory=lambda: str(uuid4()),
        primary_key=True,
        index=True,
        description="主键 UUID"
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        nullable=False,
        description="创建时间 (UTC)"
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        nullable=False,
        description="最后更新时间 (UTC)"
    )
    is_active: bool = Field(
        default=True,
        description="是否启用（逻辑删除）"
    )


# ====================================================
# ② 用户审计信息
# ====================================================
class UserTrackMixin(SQLModel):
    """记录创建者与最后修改者（外键指向 user.id）"""
    created_by_id: Optional[str] = Field(
        default=None,
        foreign_key="user.id",
        description="创建人 ID（可选）"
    )
    updated_by_id: Optional[str] = Field(
        default=None,
        foreign_key="user.id",
        description="最后修改人 ID（可选）"
    )


# ====================================================
# ③ 通用业务表基类
# ====================================================
class BaseTable(IDTimestampMixin, UserTrackMixin):
    """完整的基础表结构，用于大多数业务模型
    包括：
    id: 主键 UUID
    created_at: 创建时间
    updated_at: 最后更新时间
    is_active: 逻辑删除标志
    created_by_id: 创建人 ID
    updated_by_id: 最后修改人 ID
    """
    pass



class InvokeConfig(SQLModel):
    name: str = Field(index=True, description="调用名称")
    description: Optional[str] = Field(default=None, description="调用描述")
    parameters: Optional[dict] = Field(
        sa_column=Column("parameters", JSON),
        default=None,
        description="参数配置（JSON 格式）"
    )