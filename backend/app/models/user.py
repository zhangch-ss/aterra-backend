from sqlmodel import Field
from typing import Optional
from uuid import uuid4
from app.models.base import IDTimestampMixin
class User(IDTimestampMixin, table=True):
    """系统用户表"""
    username: str = Field(
        index=True,
        unique=True,
        max_length=50,
        description="用户名（用于登录）"
    )

    email: Optional[str] = Field(
        default=None,
        unique=True,
        description="邮箱地址（找回密码或通知）"
    )

    full_name: Optional[str] = Field(
        default=None,
        max_length=100,
        description="用户全名或昵称"
    )

    hashed_password: str = Field(
        max_length=255,
        description="加密后的密码（使用bcrypt或argon2）"
    )

    role: str = Field(
        default="user",
        description="角色类型：user / admin / editor 等"
    )


    is_superuser: bool = Field(
        default=False,
        description="是否为超级管理员（最高权限）"
    )
    organization: Optional[str] = Field(
        default=None,
        max_length=100,
        description="所属机构或研究单位"
    )

    avatar_url: Optional[str] = Field(
        default=None,
        description="头像图片地址（可选）"
    )
