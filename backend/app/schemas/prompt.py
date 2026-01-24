from typing import Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

class PromptBase(BaseModel):
    name: str
    description: Optional[str] = None
    content: str
    role: Optional[str] = Field(default=None, description="提示词角色/类型（system/user/assistant/tool/template 等）")
    scene: Optional[str] = None
    tags: Optional[list[str]] = None
    variables: Optional[dict[str, str]] = None
    version: int = 1
    visibility: Optional[str] = Field(default="private")

class PromptCreate(PromptBase):
    """
    创建 Prompt 时不再由客户端提供 user_id，后端从鉴权上下文自动注入当前用户 ID。
    """
    pass

class PromptUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    role: Optional[str] = None
    scene: Optional[str] = None
    tags: Optional[list[str]] = None
    variables: Optional[dict[str, str]] = None
    version: Optional[int] = None
    visibility: Optional[str] = None

class PromptRead(PromptBase):
    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)
