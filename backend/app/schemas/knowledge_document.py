from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class KnowledgeDocumentBase(BaseModel):
    filename: str
    bucket: str
    object_name: str
    url: str
    content_type: Optional[str] = None
    size: Optional[int] = None

    status: str = "uploaded"  # uploaded | indexed | error
    embed_provider: Optional[str] = None
    embed_model: Optional[str] = None
    chunk_size: int = 1000
    chunk_overlap: int = 200


class KnowledgeDocumentUpdate(BaseModel):
    # 主要用于调整重建索引参数或修复状态
    status: Optional[str] = None
    embed_provider: Optional[str] = None
    embed_model: Optional[str] = None
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None


class KnowledgeDocumentRead(KnowledgeDocumentBase):
    id: str
    knowledge_id: str
    user_id: str
    vector_ids: Optional[List[str]] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class KnowledgeDocumentCardOut(BaseModel):
    id: str
    filename: str
    status: str
    url: str
    content_type: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class DocumentChunkOut(BaseModel):
    page_content: str
    metadata: Dict[str, Any]
    model_config = ConfigDict(from_attributes=True)
