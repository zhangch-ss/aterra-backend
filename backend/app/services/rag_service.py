from __future__ import annotations
from typing import Optional, List, Dict, Any
import re
from langchain_core.documents import Document
from app.core.rag.chunker import chunk_texts, get_text_splitter
from app.core.rag.embeddings import get_embeddings
from app.core.rag.milvus_store import MilvusStore


class RAGService:
    """High-level RAG operations backed by Milvus and LangChain.
    Provides methods to chunk texts, upsert to Milvus, query similar docs, and delete.
    """

    @staticmethod
    def _sanitize_collection_name(name: str) -> str:
        """Sanitize collection name to meet Milvus constraints: letters, numbers, underscores only."""
        sanitized = re.sub(r"[^A-Za-z0-9_]", "_", name)
        # Ensure starts with a letter to avoid potential proxy/server-side constraints
        if not re.match(r"^[A-Za-z]", sanitized):
            sanitized = f"k_{sanitized}"
        # Milvus name length limit safeguard
        return sanitized[:255]

    def __init__(self, collection_name: str):
        self.collection_name = self._sanitize_collection_name(collection_name)

    async def _get_store(self, user_id: str, provider: Optional[str] = None, embed_model: Optional[str] = None) -> MilvusStore:
        embeddings = await get_embeddings(user_id=user_id, provider=provider, model=embed_model)
        return MilvusStore(collection_name=self.collection_name, embedding_function=embeddings)

    async def upsert_texts(
        self,
        user_id: str,
        texts: List[str],
        *,
        provider: Optional[str] = None,
        embed_model: Optional[str] = None,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        separators: Optional[List[str]] = None,
        splitter_type: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        base_metadata: dict | None = None,
    ) -> List[str]:
        splitter = get_text_splitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=separators,
            splitter_type=splitter_type or "recursive",
            params=params or None,
        )
        docs = chunk_texts(texts, splitter=splitter, base_metadata=base_metadata)
        store = await self._get_store(user_id=user_id, provider=provider, embed_model=embed_model)
        ids = store.upsert(docs)
        return ids

    async def query(
        self,
        user_id: str,
        query_text: str,
        *,
        k: int = 4,
        provider: Optional[str] = None,
        embed_model: Optional[str] = None,
        filter: Optional[str] = None,
    ) -> List[Document]:
        store = await self._get_store(user_id=user_id, provider=provider, embed_model=embed_model)
        return store.query(query_text=query_text, k=k, filter=filter)

    async def delete(self, user_id: str, ids: List[str], *, provider: Optional[str] = None, embed_model: Optional[str] = None) -> None:
        store = await self._get_store(user_id=user_id, provider=provider, embed_model=embed_model)
        store.delete(ids=ids)

    async def list_document_chunks(
        self,
        user_id: str,
        document_id: str,
        *,
        offset: int = 0,
        limit: int = 20,
        provider: Optional[str] = None,
        embed_model: Optional[str] = None,
    ) -> List[Document]:
        """
        列出指定文档（document_id）的所有分片（chunk），支持分页（offset/limit）。
        返回 LangChain Document 列表。
        """
        store = await self._get_store(user_id=user_id, provider=provider, embed_model=embed_model)
        return store.list_document_chunks(document_id=document_id, offset=offset, limit=limit)
