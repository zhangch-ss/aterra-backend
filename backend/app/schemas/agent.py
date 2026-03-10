# app/schemas/agent.py
from typing import Any, List, Optional
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict
from app.schemas.model import ModelBase
from app.schemas.knowledge import KnowledgeCardOut
# ======== 调用配置 ========
class InvokeConfig(BaseModel):
    name: str
    description: Optional[str] = None
    parameters: Optional[dict[str, Any]] = None

# ======== 基础结构（不含 id） ========
class AgentBase(BaseModel):
    name: str
    desc: Optional[str] = None
    type: str
    scene: str

# ======== 创建 ========
class AgentCreate(AgentBase):
    model_id: Optional[str] = None
    invoke_config: Optional[InvokeConfig] = None
    parent_agent_id: Optional[str] = None
    tool_ids: Optional[list[str]] = None
    knowledge_ids: Optional[list[str]] = None
    system_prompt: str | None = None
    
# ======== 更新 ========
class AgentUpdate(BaseModel):
    name: Optional[str] = None
    desc: Optional[str] = None
    invoke_config: Optional[InvokeConfig] = None
    model_id: Optional[str] = None
    parent_agent_id: Optional[str] = None
    tool_ids: Optional[list[str]] = None
    knowledge_ids: Optional[list[str]] = None

# ======== 读取（含 id） ========
class AgentRead(AgentBase):
    id: UUID
    user_id: str
    model_id: Optional[str] = None
    parent_agent_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    invoke_config: Optional[InvokeConfig] = None
    model_config = ConfigDict(from_attributes=True)
    system_prompt: str|None

# ======== 嵌套简卡（与前端一致：desc 字段名） ========
class CreateToolCardOut(BaseModel):
    id: str
    name: str
    desc: Optional[str] = None
    type: str
    model_config = ConfigDict(from_attributes=True)

# ======== 输出给前端（含关系） ========
class AgentOut(AgentRead):
    tools: Optional[list[CreateToolCardOut]] = None
    knowledges: Optional[list[KnowledgeCardOut]] = None
    subagents: Optional[list["AgentOut"]] = None
    parent_agent: Optional[dict[str, Any]] = None
    model: Optional[ModelBase] = None
    model_config = ConfigDict(from_attributes=True)

AgentOut.model_rebuild()
