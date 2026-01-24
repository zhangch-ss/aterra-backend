from __future__ import annotations
from typing import List, Sequence, Dict, Any, Optional
from langchain_core.documents import Document

# 兼容最新版与旧版 LangChain 的导入路径

from langchain_text_splitters import RecursiveCharacterTextSplitter

# 可选文本切片器（不同类型）
try:
    from langchain_text_splitters import (
        CharacterTextSplitter,
        TokenTextSplitter,
        MarkdownTextSplitter,
        CodeTextSplitter,
    )
except Exception:
    CharacterTextSplitter = None  # type: ignore
    TokenTextSplitter = None  # type: ignore
    MarkdownTextSplitter = None  # type: ignore
    CodeTextSplitter = None  # type: ignore


def get_text_splitter(
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    separators: Sequence[str] | None = None,
    splitter_type: str = "recursive",
    params: Optional[Dict[str, Any]] = None,
):
    """创建指定类型的 LangChain 文本切片器，默认使用 RecursiveCharacterTextSplitter。
    - splitter_type: 切片类型：recursive/character/token/markdown/code
    - params: 额外配置（不同类型支持的参数不同）
      - character: {"separator": "\\n\\n", "keep_separator": false}
      - token: {"encoding_name": "cl100k_base", "model_name": "gpt-3.5-turbo"}
      - markdown: {}（若不可用回退 recursive）
      - code: {"language": "python"}
    """
    params = params or {}

    # 1) 递归字符切片（默认）
    if splitter_type == "recursive":
        return RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=separators,
        )

    # 2) 简单字符切片（单一分隔符）
    if splitter_type == "character" and CharacterTextSplitter:
        sep = params.get("separator") or (separators[0] if separators else "\n\n")
        keep_sep = params.get("keep_separator", False)
        return CharacterTextSplitter(
            separator=sep,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            keep_separator=keep_sep,
        )

    # 3) Token 切片（基于 tiktoken）
    if splitter_type == "token" and TokenTextSplitter:
        encoding_name = params.get("encoding_name")
        model_name = params.get("model_name")
        return TokenTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            encoding_name=encoding_name,
            model_name=model_name,
        )

    # 4) Markdown 切片（若不可用则回退到 recursive）
    if splitter_type == "markdown" and MarkdownTextSplitter:
        return MarkdownTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    # 5) 代码切片（按语言）
    if splitter_type == "code" and CodeTextSplitter:
        language = params.get("language", "python")
        return CodeTextSplitter(
            language=language,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    # Fallback: 使用递归切片器
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=separators,
    )


def chunk_texts(
    texts: List[str],
    *,
    splitter: RecursiveCharacterTextSplitter | None = None,
    base_metadata: dict | None = None,
) -> List[Document]:
    """Split multiple raw texts into LangChain Document chunks.
    Each chunk carries metadata with source index and optional base_metadata.
    """
    splitter = splitter or get_text_splitter()
    documents: List[Document] = []
    for idx, txt in enumerate(texts):
        metas = base_metadata.copy() if base_metadata else {}
        metas.update({"source_index": idx})
        docs = splitter.create_documents([txt], metadatas=[metas])
        documents.extend(docs)
    return documents
