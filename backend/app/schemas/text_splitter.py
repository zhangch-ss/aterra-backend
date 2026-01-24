from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class TextSplitterBase(BaseModel):
    name: str
    description: Optional[str] = Field(default=None, alias="desc")
    chunk_size: int = 1000
    chunk_overlap: int = 200
    separators: Optional[List[str]] = None
    splitter_type: str = "recursive"
    params: Optional[Dict[str, Any]] = None
    is_default: bool = False
    model_config = ConfigDict(populate_by_name=True)


class TextSplitterCreateInput(TextSplitterBase):
    # name 必填，其他字段已在基类给出默认
    pass


class TextSplitterUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = Field(default=None, alias="desc")
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    separators: Optional[List[str]] = None
    splitter_type: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    is_default: Optional[bool] = None
    model_config = ConfigDict(populate_by_name=True)


class TextSplitterRead(BaseModel):
    id: str
    user_id: Optional[str] = None
    name: str
    description: Optional[str] = None
    chunk_size: int
    chunk_overlap: int
    separators: Optional[List[str]] = None
    splitter_type: str
    params: Optional[Dict[str, Any]] = None
    is_default: bool = False
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class TextSplitterCardOut(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    is_default: bool = False
    model_config = ConfigDict(from_attributes=True)
