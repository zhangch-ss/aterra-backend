from typing import Optional, List
from sqlalchemy import Column, JSON
from sqlmodel import SQLModel, Field
from app.models.base import BaseTable


class KnowledgeDocument(BaseTable, table=True):
    """
    知识库文档表：每个知识库可包含多个文档，文档文件存储在 MinIO，中间状态与索引信息记录在此。
    - 文件上传后记录 MinIO 存储信息（bucket、object_name、url、content_type、size）
    - 支持后续将文档解析为文本并分块，生成向量并入库（Milvus），保存返回的 vector_ids
    - 记录索引状态（uploaded | indexed | error）及错误信息，支持重新索引/删除
    """
    __tablename__ = "knowledge_document"
    # 归属信息
    knowledge_id: str = Field(foreign_key="knowledge.id", index=True, description="关联知识库 ID")
    user_id: Optional[str] = Field(default=None, foreign_key="user.id", index=True, description="所属用户 ID")

    # 文件元信息
    filename: str = Field(description="原始文件名")
    bucket: str = Field(description="MinIO 桶名")
    object_name: str = Field(description="MinIO 对象名（带前缀的唯一键）", index=True)
    url: str = Field(description="文件可访问（预签名）URL")
    content_type: Optional[str] = Field(default=None, description="MIME 类型")
    size: Optional[int] = Field(default=None, description="文件大小（字节）")

    # 索引与嵌入参数
    status: str = Field(default="uploaded", description="处理状态：uploaded | indexed | error", index=True)
    embed_provider: Optional[str] = Field(default=None, description="嵌入提供商（如 openai/azure 等）")
    embed_model: Optional[str] = Field(default=None, description="嵌入模型名")
    chunk_size: int = Field(default=1000, description="分块大小")
    chunk_overlap: int = Field(default=200, description="分块重叠大小")

    # 索引结果与错误信息
    vector_ids: Optional[List[str]] = Field(
        sa_column=Column("vector_ids", JSON),
        default=None,
        description="向量 ID 列表（Milvus 返回的主键）"
    )
    error: Optional[str] = Field(default=None, description="错误信息（仅在状态为 error 时记录）")
