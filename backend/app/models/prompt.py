from typing import Optional, List, Dict
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, JSON
from app.models.base import BaseTable

class Prompt(BaseTable, table=True):
    """📝 Prompt 模板表
    支持按用户维护可复用的系统/用户/工具等提示词模板。
    """
    __tablename__ = "prompt"

    user_id: Optional[str] = Field(default=None, foreign_key="user.id", index=True, description="所属用户 ID")
    name: str = Field(index=True, max_length=100, description="模板名称")
    description: Optional[str] = Field(default=None, description="模板描述")

    # 核心内容
    content: str = Field(description="提示词内容（可包含变量占位符，如 {context}）")

    # 类型/角色（如 system/user/assistant/tool/template 等）
    role: Optional[str] = Field(default=None, index=True, description="提示词角色/类型")

    # 适用场景（可选）
    scene: Optional[str] = Field(default=None, index=True, description="适用场景")

    # 标签与变量占位符
    tags: Optional[List[str]] = Field(default=None, sa_column=Column(JSON), description="标签列表")
    variables: Optional[Dict[str, str]] = Field(default=None, sa_column=Column(JSON), description="变量说明（占位符->描述）")

    # 版本与可见性
    version: int = Field(default=1, description="版本号")
    visibility: Optional[str] = Field(default="private", description="可见性（private/public/system）")
