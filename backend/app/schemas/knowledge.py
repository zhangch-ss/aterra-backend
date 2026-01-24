from typing import Optional, Any
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict

class KnowledgeBase(BaseModel):
    name: str
    description: Optional[str] = None

class KnowledgeCreate(KnowledgeBase):
    """
    创建 Knowledge 时不由客户端提供 user_id，后端从鉴权上下文自动注入当前用户 ID。
    """
    pass

class KnowledgeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None

class KnowledgeRead(KnowledgeBase):
    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

class KnowledgeCardOut(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)
