from typing import Optional, List, Dict, Any
from sqlmodel import Field, SQLModel
from sqlalchemy import Column, JSON, UniqueConstraint
from app.models.base import BaseTable


class TextSplitter(BaseTable, table=True):
    """
    文本切片器配置表：用于管理每个用户的文本切分策略（chunk_size/overlap/separators），
    可在知识库入库时复用，确保一致的切分配置与可视化“卡片”管理。
    """
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_text_splitter_user_name"),
    )
    __tablename__ = "text_splitter"

    user_id: Optional[str] = Field(
        default=None,
        foreign_key="user.id",
        index=True,
        description="所属用户 ID",
    )
    name: str = Field(
        index=True,
        max_length=100,
        description="切片器名称（唯一约束：同一用户下 name 不重复）",
    )
    description: Optional[str] = Field(default=None, description="切片器描述")

    chunk_size: int = Field(default=1000, ge=1, description="每个分片的最大字符数")
    chunk_overlap: int = Field(default=200, ge=0, description="分片之间的重叠字符数")
    # 分隔符序列（可选），按优先级依次尝试；与 langchain_text_splitters 的 separators 参数一致
    separators: Optional[List[str]] = Field(
        default=None,
        sa_column=Column(JSON),
        description="分隔符序列（JSON 数组），例如 ['\\n\\n', '\\n', '。', '，', ' ']",
    )

    splitter_type: str = Field(
        default="recursive",
        max_length=50,
        description="切片器类型：recursive/token/markdown/html/code 等",
    )
    params: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON),
        description="方法特定参数（JSON 对象）",
    )

    is_default: bool = Field(default=False, description="是否为该用户的默认切片器")
