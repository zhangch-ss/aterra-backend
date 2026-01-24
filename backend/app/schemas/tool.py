# app/schemas/tool.py
from typing import Any, Optional
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict

class InvokeConfig(BaseModel):
    name: str
    description: Optional[str] = None
    parameters: Optional[dict[str, Any]] = None

from app.models.tool import ToolTypeEnum

class ToolBase(BaseModel):
    name: str
    description: Optional[str] = None  # ✅ 与 DB 字段一致
    type: ToolTypeEnum
    scene: Optional[str] = None

class ToolCreate(ToolBase):
    user_id: str
    invoke_config: Optional[InvokeConfig] = None

class ToolUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    invoke_config: Optional[InvokeConfig] = None

class ToolRead(ToolBase):
    id: UUID
    user_id: str
    model_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    invoke_config: Optional[InvokeConfig] = None
    model_config = ConfigDict(from_attributes=True)


class ToolTypeOut(BaseModel):
    id: int
    name: str
    description: str | None = None

    model_config = ConfigDict(from_attributes=True)

class CreateToolCardOut(BaseModel):
    id: str
    name: str
    description: str | None = None
    type: str

class ToolDetailOut(BaseModel):
    id: str
    user_id: str | None = None
    name: str
    description: str | None = None
    type: ToolTypeEnum
    scene: str | None = None
    enabled: bool | None = None
    module: str | None = None
    function: str | None = None

    # 运行时默认值容器与入库的 schema
    invoke_config: Optional[InvokeConfig] = None
    tool_schema: dict | None = None
    runtime_parameters: dict | None = None


    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
