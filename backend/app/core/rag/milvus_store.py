from __future__ import annotations
from typing import Optional, List
try:
    # Prefer official langchain-milvus package
    from langchain_milvus import Milvus as MilvusVectorStore  # type: ignore
except ImportError:
    # Fallback for environments where vectorstores moved to community package
    from langchain_community.vectorstores import Milvus as MilvusVectorStore  # type: ignore
from langchain_core.documents import Document
from app.core.config import settings
import time
import requests
from pymilvus.exceptions import MilvusException
from pymilvus import MilvusClient


class MilvusStore:
    """Thin wrapper around LangChain Milvus vector store.
    Uses langchain-milvus MilvusVectorStore and exposes upsert/query/delete operations.
    """

    def __init__(
        self,
        collection_name: str,
        embedding_function,
        *,
        auto_id: bool = True,
        text_field: str = "text",
    ):
        self.collection_name = collection_name
        self.embedding_function = embedding_function
        # Connection args from settings
        # Build connection args; prefer explicit HTTP(S) uri so pymilvus does not default to localhost
        scheme = "https" if bool(getattr(settings, "MILVUS_TLS", False)) else "http"
        uri = f"{scheme}://{settings.MILVUS_HOST}:{settings.MILVUS_PORT}"
        conn_args = {"uri": uri}
        if getattr(settings, "MILVUS_USER", None):
            conn_args["user"] = settings.MILVUS_USER  # type: ignore[assignment]
        if getattr(settings, "MILVUS_PASSWORD", None):
            conn_args["password"] = settings.MILVUS_PASSWORD  # type: ignore[assignment]
        if getattr(settings, "MILVUS_DB", None):
            conn_args["db_name"] = settings.MILVUS_DB  # type: ignore[assignment]
        self.connection_args = conn_args
        self.text_field = text_field
        self.auto_id = auto_id
        self._store: Optional[MilvusVectorStore] = None

    def _wait_ready(self, timeout: int = 120, interval: float = 2.0) -> None:
        """Poll Milvus Proxy health endpoint until ready to avoid 'Proxy is not ready yet' errors."""
        scheme = "https" if bool(getattr(settings, "MILVUS_TLS", False)) else "http"
        url = f"{scheme}://{settings.MILVUS_HOST}:9091/healthz"
        deadline = time.time() + timeout
        last_err: Optional[Exception] = None
        while time.time() < deadline:
            try:
                resp = requests.get(url, timeout=3)
                if resp.status_code == 200:
                    return
            except Exception as e:
                last_err = e
            time.sleep(interval)
        raise RuntimeError(f"Milvus Proxy not ready within {timeout}s: url={url}, last_err={last_err}")

    def _connect_with_retry(self, retries: int = 6, base_delay: float = 2.0) -> MilvusVectorStore:
        """建立与 Milvus 的连接并在 Proxy 未就绪时进行指数退避重试。"""
        # 初次等待 Proxy 就绪
        self._wait_ready(timeout=180)
        delay = base_delay
        for _ in range(retries):
            try:
                return MilvusVectorStore(
                    embedding_function=self.embedding_function,
                    collection_name=self.collection_name,
                    connection_args=self.connection_args,
                    auto_id=self.auto_id,
                    text_field=self.text_field,
                )
            except MilvusException as e:
                msg = str(e)
                if "Proxy is not ready" in msg or "service unavailable" in msg:
                    time.sleep(delay)
                    # 再次轮询健康并加大等待时间
                    self._wait_ready(timeout=int(delay * 2))
                    delay = min(delay * 2, 30.0)
                    continue
                # 非就绪错误，直接抛出
                raise
        raise RuntimeError("Milvus Proxy not ready after retries")

    def _get_store(self) -> MilvusVectorStore:
        if self._store is None:
            self._store = self._connect_with_retry()
        return self._store

    # Upsert documents (add or update)
    def upsert(self, docs: List[Document]) -> List[str]:
        store = self._get_store()
        ids = store.add_documents(docs)
        return [str(i) for i in ids]

    # Similarity search
    def query(self, query_text: str, k: int = 4, filter: Optional[str] = None) -> List[Document]:
        store = self._get_store()
        # Workaround: langchain-milvus/pymilvus may pass `filter` twice to MilvusClient.search, causing
        # "multiple values for keyword argument 'filter'". Avoid passing filter when it is None/empty.
        if filter is None or (isinstance(filter, str) and filter.strip() == ""):
            return store.similarity_search(query_text, k=k)
        return store.similarity_search(query_text, k=k, filter=filter)

    # List chunks by document_id with offset/limit
    def list_document_chunks(self, document_id: str, offset: int = 0, limit: int = 20) -> List[Document]:
        """
        按文档 ID 查询其所有分片（chunk），支持分页（offset/limit）。
        返回 Document 列表（包含 page_content 与 metadata）。
        兼容不同版本的 LangChain-Milvus/集合 schema（metadata/attrs/扁平字段）。
        """
        # 使用 pymilvus MilvusClient 进行查询，兼容不同版本 schema（metadata/attrs/扁平字段）
        scheme = "https" if bool(getattr(settings, "MILVUS_TLS", False)) else "http"
        uri = f"{scheme}://{settings.MILVUS_HOST}:{settings.MILVUS_PORT}"
        client_kwargs = {"uri": uri}
        if getattr(settings, "MILVUS_USER", None):
            client_kwargs["user"] = settings.MILVUS_USER  # type: ignore[assignment]
        if getattr(settings, "MILVUS_PASSWORD", None):
            client_kwargs["password"] = settings.MILVUS_PASSWORD  # type: ignore[assignment]
        if getattr(settings, "MILVUS_DB", None):
            client_kwargs["db_name"] = settings.MILVUS_DB  # type: ignore[assignment]
        client = MilvusClient(**client_kwargs)

        # 依次尝试不同字段命名
        tries: list[tuple[str, list[str], Optional[str]]] = [
            (f'attrs["document_id"] == "{document_id}"', [self.text_field, "attrs"], "attrs"),
            (f'metadata["document_id"] == "{document_id}"', [self.text_field, "metadata"], "metadata"),
            (f'document_id == "{document_id}"', [self.text_field, "document_id", "filename", "knowledge_id", "user_id", "source_index"], None),
        ]
        last_err: Optional[Exception] = None
        rows: list[dict] = []
        meta_field_used: Optional[str] = None

        for expr, out_fields, meta_field in tries:
            try:
                rows = client.query(
                    collection_name=self.collection_name,
                    filter=expr,
                    output_fields=out_fields,
                    limit=limit,
                    offset=offset,
                )
                meta_field_used = meta_field
                # 查询成功则跳出
                break
            except Exception as e:
                last_err = e
                rows = []
                continue

        if not rows:
            if last_err:
                # 抛出最后一次错误，便于定位
                raise last_err
            return []

        docs: List[Document] = []
        for r in rows:
            if meta_field_used and meta_field_used in r:
                meta = r.get(meta_field_used, {}) or {}
            else:
                # 扁平字段回填为元数据（尽力而为）
                possible_keys = ["document_id", "filename", "knowledge_id", "user_id", "source_index"]
                meta = {k: r.get(k) for k in possible_keys if k in r}
            docs.append(Document(page_content=r.get(self.text_field, ""), metadata=meta))
        return docs

    # Delete by ids
    def delete(self, ids: List[str]) -> None:
        store = self._get_store()
        store.delete(ids=ids)
