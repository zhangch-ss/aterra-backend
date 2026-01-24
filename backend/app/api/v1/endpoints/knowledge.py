from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from typing import Optional, List, Dict, Any
from pydantic import BaseModel

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.knowledge import Knowledge
from app.schemas.knowledge import KnowledgeCreate, KnowledgeUpdate, KnowledgeRead
from app.crud.knowledge_crud import crud_knowledge
from app.services.rag_service import RAGService
from app.utils.minio_client import MinioClient
from app.core.config import settings
from app.crud.knowledge_document_crud import crud_knowledge_document
from app.crud.text_splitter_crud import crud_text_splitter
from app.schemas.knowledge_document import (
    KnowledgeDocumentRead,
    KnowledgeDocumentCardOut,
    KnowledgeDocumentUpdate,
    DocumentChunkOut,
)

router = APIRouter()

# 创建知识库
@router.post("/create", response_model=KnowledgeRead)
async def create_knowledge(
    payload: KnowledgeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    obj = Knowledge(**payload.dict(), user_id=current_user.id)
    created = await crud_knowledge.create(obj_in=obj, db_session=db)
    return KnowledgeRead.model_validate(created, from_attributes=True)

# 更新知识库
@router.put("/{knowledge_id}", response_model=KnowledgeRead)
async def update_knowledge(
    knowledge_id: str,
    payload: KnowledgeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    knowledge = await crud_knowledge.get(id=knowledge_id, db_session=db)
    if not knowledge:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if knowledge.user_id != current_user.id and not getattr(current_user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="无权限修改该知识库")

    updated = await crud_knowledge.update(obj_current=knowledge, obj_new=payload, db_session=db)
    return KnowledgeRead.model_validate(updated, from_attributes=True)

# 删除知识库
@router.delete("/{knowledge_id}", response_model=dict)
async def delete_knowledge(
    knowledge_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    knowledge = await crud_knowledge.get(id=knowledge_id, db_session=db)
    if not knowledge:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if knowledge.user_id != current_user.id and not getattr(current_user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="无权限删除该知识库")

    await crud_knowledge.remove(id=knowledge_id, db_session=db)
    # 注意：RAG 删除向量未实现持久化 ids，这里暂不清理。后续可扩展为按 knowledge_id 维护集合/ids。
    return {"ok": True}

# 列出当前用户的知识库（支持关键词搜索 + 简单分页）
@router.get("/list", response_model=List[KnowledgeRead])
async def list_knowledges(
    keyword: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 使用基础分页：构造查询并按用户过滤
    stmt = select(Knowledge).where(Knowledge.user_id == current_user.id)
    if keyword:
        from sqlalchemy import or_
        stmt = stmt.where(
            or_(Knowledge.name.ilike(f"%{keyword}%"), Knowledge.description.ilike(f"%{keyword}%"))
        )
    # 分页
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    res = await db.execute(stmt)
    items = res.scalars().all()
    return [KnowledgeRead.model_validate(i, from_attributes=True) for i in items]

# 获取单个知识库
@router.get("/{knowledge_id}", response_model=KnowledgeRead)
async def get_knowledge(
    knowledge_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    knowledge = await crud_knowledge.get(id=knowledge_id, db_session=db)
    if not knowledge:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if knowledge.user_id != current_user.id and not getattr(current_user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="无权限查看该知识库")
    return KnowledgeRead.model_validate(knowledge, from_attributes=True)



# RAG: 向知识库集合中插入/更新文本（返回向量 ids）
class UpsertTextsPayload(BaseModel):
    texts: List[str]
    provider: Optional[str] = None
    embed_model: Optional[str] = None
    chunk_size: int = 1000
    chunk_overlap: int = 200
    splitter_id: Optional[str] = None
    separators: Optional[List[str]] = None
    splitter_type: Optional[str] = None
    params: Optional[Dict[str, Any]] = None

@router.post("/{knowledge_id}/upsert_texts", response_model=dict)
async def upsert_texts(
    knowledge_id: str,
    payload: UpsertTextsPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    knowledge = await crud_knowledge.get(id=knowledge_id, db_session=db)
    if not knowledge:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if knowledge.user_id != current_user.id and not getattr(current_user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="无权限写入该知识库")

    rag = RAGService(collection_name=f"knowledge_{knowledge_id}")
    # 计算切片参数（支持 splitter_id 与自定义 separators/type/params）
    eff_chunk_size = payload.chunk_size
    eff_chunk_overlap = payload.chunk_overlap
    eff_separators = payload.separators
    eff_splitter_type = payload.splitter_type
    eff_params = payload.params

    if payload.splitter_id:
        ts = await crud_text_splitter.get(id=payload.splitter_id, db_session=db)
        if not ts:
            raise HTTPException(status_code=404, detail="切片器不存在")
        if ts.user_id != current_user.id and not getattr(current_user, "is_superuser", False):
            raise HTTPException(status_code=403, detail="无权限使用该切片器")
        eff_chunk_size = ts.chunk_size
        eff_chunk_overlap = ts.chunk_overlap
        if eff_separators is None:
            eff_separators = ts.separators
        if eff_splitter_type is None:
            eff_splitter_type = getattr(ts, "splitter_type", None)
        if eff_params is None:
            eff_params = getattr(ts, "params", None)

    # 默认切片器回退
    if eff_separators is None and not payload.splitter_id:
        ts_def = await crud_text_splitter.get_default_by_user_id(user_id=current_user.id, db_session=db)
        if ts_def:
            eff_chunk_size = ts_def.chunk_size
            eff_chunk_overlap = ts_def.chunk_overlap
            eff_separators = ts_def.separators
            if eff_splitter_type is None:
                eff_splitter_type = getattr(ts_def, "splitter_type", None)
            if eff_params is None:
                eff_params = getattr(ts_def, "params", None)

    ids = await rag.upsert_texts(
        user_id=current_user.id,
        texts=payload.texts,
        provider=payload.provider,
        embed_model=payload.embed_model,
        chunk_size=eff_chunk_size,
        chunk_overlap=eff_chunk_overlap,
        separators=eff_separators,
        splitter_type=eff_splitter_type,
        params=eff_params,
        base_metadata={"knowledge_id": knowledge_id, "user_id": current_user.id},
    )
    return {"ids": ids}

# RAG: 相似搜索
@router.get("/{knowledge_id}/search", response_model=list[dict])
async def search_texts(
    knowledge_id: str,
    query: str,
    k: int = 4,
    provider: Optional[str] = None,
    embed_model: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    knowledge = await crud_knowledge.get(id=knowledge_id, db_session=db)
    if not knowledge:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if knowledge.user_id != current_user.id and not getattr(current_user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="无权限查询该知识库")

    rag = RAGService(collection_name=f"knowledge_{knowledge_id}")
    docs = await rag.query(
        user_id=current_user.id,
        query_text=query,
        k=k,
        provider=provider,
        embed_model=embed_model,
        filter=None,
    )
    # 将 Document 转为可序列化 dict
    out = [{"page_content": d.page_content, "metadata": d.metadata} for d in docs]
    return out


def _get_minio_client() -> MinioClient:
    return MinioClient(
            minio_url=settings.MINIO_URL,
            access_key=settings.MINIO_ROOT_USER,
            secret_key=settings.MINIO_ROOT_PASSWORD,
            bucket_name=settings.MINIO_BUCKET,
            internal_url=settings.MINIO_INTERNAL_URL,
    )



def _bytes_to_text(data: bytes, filename: str, content_type: Optional[str] = None) -> str:
    """
    简单的字节到文本转换，优先 utf-8，回退 gbk，最后忽略不可解码字节。
    后续可扩展 PDF/DOCX 解析。
    """
    # 纯文本/Markdown 直接按 utf-8 解析
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return data.decode("gbk")
        except Exception:
            return data.decode("utf-8", errors="ignore")


@router.post("/{knowledge_id}/documents/upload", response_model=KnowledgeDocumentRead)
async def upload_document(
    knowledge_id: str,
    file: UploadFile = File(...),
    index_now: bool = Query(False, description="上传后立即入库到向量库"),
    provider: Optional[str] = None,
    embed_model: Optional[str] = None,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    splitter_id: Optional[str] = None,
    separators: Optional[List[str]] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 权限校验
    knowledge = await crud_knowledge.get(id=knowledge_id, db_session=db)
    if not knowledge:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if knowledge.user_id != current_user.id and not getattr(current_user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="无权限上传到该知识库")

    # 计算切片参数（支持 splitter_id 与自定义 separators/type/params）
    eff_chunk_size = chunk_size
    eff_chunk_overlap = chunk_overlap
    eff_separators = separators
    eff_splitter_type = None
    eff_params = None
    if splitter_id:
        ts = await crud_text_splitter.get(id=splitter_id, db_session=db)
        if not ts:
            raise HTTPException(status_code=404, detail="切片器不存在")
        if ts.user_id != current_user.id and not getattr(current_user, "is_superuser", False):
            raise HTTPException(status_code=403, detail="无权限使用该切片器")
        eff_chunk_size = ts.chunk_size
        eff_chunk_overlap = ts.chunk_overlap
        if eff_separators is None:
            eff_separators = ts.separators
        if eff_splitter_type is None:
            eff_splitter_type = getattr(ts, "splitter_type", None)
        if eff_params is None:
            eff_params = getattr(ts, "params", None)

    # 默认切片器回退
    if eff_separators is None and not splitter_id:
        ts_def = await crud_text_splitter.get_default_by_user_id(user_id=current_user.id, db_session=db)
        if ts_def:
            eff_chunk_size = ts_def.chunk_size
            eff_chunk_overlap = ts_def.chunk_overlap
            eff_separators = ts_def.separators
            if eff_splitter_type is None:
                eff_splitter_type = getattr(ts_def, "splitter_type", None)
            if eff_params is None:
                eff_params = getattr(ts_def, "params", None)

    # 上传到 MinIO
    minio = _get_minio_client()
    try:
        put_resp = minio.put_object(file.file, file.filename, file.content_type)
        s = minio.stat_object(bucket_name=put_resp.bucket_name, object_name=put_resp.file_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"MinIO 上传失败: {repr(e)}")

    # 创建文档记录
    doc_in = {
        "knowledge_id": knowledge_id,
        "user_id": current_user.id,
        "filename": file.filename,
        "bucket": put_resp.bucket_name,
        "object_name": put_resp.file_name,
        "url": put_resp.url,
        "content_type": file.content_type,
        "size": getattr(s, "size", None),
        "status": "uploaded",
        "embed_provider": provider,
        "embed_model": embed_model,
        "chunk_size": eff_chunk_size,
        "chunk_overlap": eff_chunk_overlap,
    }
    created = await crud_knowledge_document.create(obj_in=doc_in, created_by_id=current_user.id, db_session=db)

    # 可选：立即入库到向量库
    if index_now:
        try:
            data = minio.get_object_bytes(bucket_name=put_resp.bucket_name, object_name=put_resp.file_name)
            text = _bytes_to_text(data, file.filename, file.content_type)
            rag = RAGService(collection_name=f"knowledge_{knowledge_id}")
            ids = await rag.upsert_texts(
                user_id=current_user.id,
                texts=[text],
                provider=provider,
                embed_model=embed_model,
                chunk_size=eff_chunk_size,
                chunk_overlap=eff_chunk_overlap,
                separators=eff_separators,
                splitter_type=eff_splitter_type,
                params=eff_params,
                base_metadata={
                    "knowledge_id": knowledge_id,
                    "user_id": current_user.id,
                    "document_id": created.id,
                    "filename": file.filename,
                },
            )
            updated = await crud_knowledge_document.update(
                obj_current=created,
                obj_new={"status": "indexed", "vector_ids": ids},
                db_session=db,
            )
            return KnowledgeDocumentRead.model_validate(updated, from_attributes=True)
        except ValueError as e:
            updated = await crud_knowledge_document.update(
                obj_current=created,
                obj_new={"status": "error", "error": repr(e)},
                db_session=db,
            )
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            # 标记错误状态
            updated = await crud_knowledge_document.update(
                obj_current=created,
                obj_new={"status": "error", "error": repr(e)},
                db_session=db,
            )
            raise HTTPException(status_code=500, detail=f"索引失败: {repr(e)}")

    return KnowledgeDocumentRead.model_validate(created, from_attributes=True)


@router.post("/{knowledge_id}/documents/batch_upload", response_model=List[KnowledgeDocumentRead])
async def batch_upload_documents(
    knowledge_id: str,
    files: List[UploadFile] = File(...),
    index_now: bool = Query(False, description="上传后立即入库到向量库（批量）"),
    provider: Optional[str] = None,
    embed_model: Optional[str] = None,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    splitter_id: Optional[str] = None,
    separators: Optional[List[str]] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 权限校验
    knowledge = await crud_knowledge.get(id=knowledge_id, db_session=db)
    if not knowledge:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if knowledge.user_id != current_user.id and not getattr(current_user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="无权限上传到该知识库")

    # 计算切片参数（支持 splitter_id 与自定义 separators/type/params）
    eff_chunk_size = chunk_size
    eff_chunk_overlap = chunk_overlap
    eff_separators = separators
    eff_splitter_type = None
    eff_params = None
    if splitter_id:
        ts = await crud_text_splitter.get(id=splitter_id, db_session=db)
        if not ts:
            raise HTTPException(status_code=404, detail="切片器不存在")
        if ts.user_id != current_user.id and not getattr(current_user, "is_superuser", False):
            raise HTTPException(status_code=403, detail="无权限使用该切片器")
        eff_chunk_size = ts.chunk_size
        eff_chunk_overlap = ts.chunk_overlap
        if eff_separators is None:
            eff_separators = ts.separators
        if eff_splitter_type is None:
            eff_splitter_type = getattr(ts, "splitter_type", None)
        if eff_params is None:
            eff_params = getattr(ts, "params", None)

    # 默认切片器回退
    if eff_separators is None and not splitter_id:
        ts_def = await crud_text_splitter.get_default_by_user_id(user_id=current_user.id, db_session=db)
        if ts_def:
            eff_chunk_size = ts_def.chunk_size
            eff_chunk_overlap = ts_def.chunk_overlap
            eff_separators = ts_def.separators
            if eff_splitter_type is None:
                eff_splitter_type = getattr(ts_def, "splitter_type", None)
            if eff_params is None:
                eff_params = getattr(ts_def, "params", None)

    minio = _get_minio_client()
    results: List[KnowledgeDocumentRead] = []

    for f in files:
        # 每个文件独立处理：上传 -> 记录 -> 可选索引
        try:
            put_resp = minio.put_object(f.file, f.filename, f.content_type)
            s = minio.stat_object(bucket_name=put_resp.bucket_name, object_name=put_resp.file_name)
        except Exception as e:
            # 批量接口遇到上传失败直接抛错（可根据需求调整为“跳过失败项继续”）
            raise HTTPException(status_code=500, detail=f"MinIO 上传失败: {repr(e)}")

        doc_in = {
            "knowledge_id": knowledge_id,
            "user_id": current_user.id,
            "filename": f.filename,
            "bucket": put_resp.bucket_name,
            "object_name": put_resp.file_name,
            "url": put_resp.url,
            "content_type": f.content_type,
            "size": getattr(s, "size", None),
            "status": "uploaded",
            "embed_provider": provider,
            "embed_model": embed_model,
            "chunk_size": eff_chunk_size,
            "chunk_overlap": eff_chunk_overlap,
        }
        created = await crud_knowledge_document.create(obj_in=doc_in, created_by_id=current_user.id, db_session=db)

        if index_now:
            try:
                data = minio.get_object_bytes(bucket_name=put_resp.bucket_name, object_name=put_resp.file_name)
                text = _bytes_to_text(data, f.filename, f.content_type)
                rag = RAGService(collection_name=f"knowledge_{knowledge_id}")
                ids = await rag.upsert_texts(
                    user_id=current_user.id,
                    texts=[text],
                    provider=provider,
                    embed_model=embed_model,
                    chunk_size=eff_chunk_size,
                    chunk_overlap=eff_chunk_overlap,
                    separators=eff_separators,
                    splitter_type=eff_splitter_type,
                    params=eff_params,
                    base_metadata={
                        "knowledge_id": knowledge_id,
                        "user_id": current_user.id,
                        "document_id": created.id,
                        "filename": f.filename,
                    },
                )
                created = await crud_knowledge_document.update(
                    obj_current=created,
                    obj_new={"status": "indexed", "vector_ids": ids},
                    db_session=db,
                )
            except ValueError as e:
                created = await crud_knowledge_document.update(
                    obj_current=created,
                    obj_new={"status": "error", "error": repr(e)},
                    db_session=db,
                )
            except Exception as e:
                created = await crud_knowledge_document.update(
                    obj_current=created,
                    obj_new={"status": "error", "error": repr(e)},
                    db_session=db,
                )

        results.append(KnowledgeDocumentRead.model_validate(created, from_attributes=True))

    return results

@router.get("/{knowledge_id}/documents", response_model=List[KnowledgeDocumentCardOut])
async def list_documents(
    knowledge_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    knowledge = await crud_knowledge.get(id=knowledge_id, db_session=db)
    if not knowledge:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if knowledge.user_id != current_user.id and not getattr(current_user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="无权限查看该知识库")

    docs = await crud_knowledge_document.list_by_knowledge(
        knowledge_id=knowledge_id, user_id=current_user.id, db_session=db
    )
    return [KnowledgeDocumentCardOut.model_validate(d, from_attributes=True) for d in docs]


@router.get("/{knowledge_id}/documents/{doc_id}", response_model=KnowledgeDocumentRead)
async def get_document(
    knowledge_id: str,
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    knowledge = await crud_knowledge.get(id=knowledge_id, db_session=db)
    if not knowledge:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if knowledge.user_id != current_user.id and not getattr(current_user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="无权限查看该知识库")

    doc = await crud_knowledge_document.get_by_knowledge_and_id(
        knowledge_id=knowledge_id, doc_id=doc_id, user_id=current_user.id, db_session=db
    )
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    return KnowledgeDocumentRead.model_validate(doc, from_attributes=True)


@router.get("/{knowledge_id}/documents/{doc_id}/chunks", response_model=List[DocumentChunkOut])
async def list_document_chunks(
    knowledge_id: str,
    doc_id: str,
    offset: int = 0,
    limit: int = 20,
    provider: Optional[str] = None,
    embed_model: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    列出指定文档的所有嵌入分片（chunk），支持分页（offset/limit）。
    返回每个分片的 page_content 与 metadata（包含写入时的元数据，例如 document_id/filename 等）。
    """
    knowledge = await crud_knowledge.get(id=knowledge_id, db_session=db)
    if not knowledge:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if knowledge.user_id != current_user.id and not getattr(current_user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="无权限查看该知识库")

    doc = await crud_knowledge_document.get_by_knowledge_and_id(
        knowledge_id=knowledge_id, doc_id=doc_id, user_id=current_user.id, db_session=db
    )
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    rag = RAGService(collection_name=f"knowledge_{knowledge_id}")
    chunks = await rag.list_document_chunks(
        user_id=current_user.id,
        document_id=doc_id,
        offset=max(offset, 0),
        limit=max(min(limit, 200), 1),  # 简单限制单次返回 1~200
        provider=provider or doc.embed_provider,
        embed_model=embed_model or doc.embed_model,
    )
    return [DocumentChunkOut(page_content=d.page_content, metadata=d.metadata) for d in chunks]


@router.delete("/{knowledge_id}/documents/{doc_id}", response_model=dict)
async def delete_document(
    knowledge_id: str,
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    knowledge = await crud_knowledge.get(id=knowledge_id, db_session=db)
    if not knowledge:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if knowledge.user_id != current_user.id and not getattr(current_user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="无权限删除该知识库文档")

    doc = await crud_knowledge_document.get_by_knowledge_and_id(
        knowledge_id=knowledge_id, doc_id=doc_id, user_id=current_user.id, db_session=db
    )
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    # 删除向量
    try:
        if doc.vector_ids:
            rag = RAGService(collection_name=f"knowledge_{knowledge_id}")
            await rag.delete(user_id=current_user.id, ids=doc.vector_ids)
    except Exception:
        # 向量删除失败不阻断文件和记录删除
        pass

    # 删除 MinIO 对象
    try:
        minio = _get_minio_client()
        minio.remove_object(bucket_name=doc.bucket, object_name=doc.object_name)
    except Exception:
        pass

    # 删除记录
    await crud_knowledge_document.remove(id=doc_id, db_session=db)
    return {"ok": True}


@router.post("/{knowledge_id}/documents/{doc_id}/reindex", response_model=KnowledgeDocumentRead)
async def reindex_document(
    knowledge_id: str,
    doc_id: str,
    provider: Optional[str] = None,
    embed_model: Optional[str] = None,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    splitter_id: Optional[str] = None,
    separators: Optional[List[str]] = None,
    splitter_type: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    knowledge = await crud_knowledge.get(id=knowledge_id, db_session=db)
    if not knowledge:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if knowledge.user_id != current_user.id and not getattr(current_user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="无权限操作该知识库")

    doc = await crud_knowledge_document.get_by_knowledge_and_id(
        knowledge_id=knowledge_id, doc_id=doc_id, user_id=current_user.id, db_session=db
    )
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    minio = _get_minio_client()
    try:
        data = minio.get_object_bytes(bucket_name=doc.bucket, object_name=doc.object_name)
        text = _bytes_to_text(data, doc.filename, doc.content_type)
        rag = RAGService(collection_name=f"knowledge_{knowledge_id}")

        # 计算切片参数（优先请求参数，其次切片器，最后回落到文档记录）
        eff_chunk_size = chunk_size or doc.chunk_size
        eff_chunk_overlap = chunk_overlap or doc.chunk_overlap
        eff_separators = separators
        eff_splitter_type = splitter_type
        eff_params = params

        if splitter_id:
            ts = await crud_text_splitter.get(id=splitter_id, db_session=db)
            if not ts:
                raise HTTPException(status_code=404, detail="切片器不存在")
            if ts.user_id != current_user.id and not getattr(current_user, "is_superuser", False):
                raise HTTPException(status_code=403, detail="无权限使用该切片器")
            eff_chunk_size = ts.chunk_size
            eff_chunk_overlap = ts.chunk_overlap
            if eff_separators is None:
                eff_separators = ts.separators
            if eff_splitter_type is None:
                eff_splitter_type = getattr(ts, "splitter_type", None)
            if eff_params is None:
                eff_params = getattr(ts, "params", None)

        # 默认切片器回退
        if eff_separators is None and not splitter_id:
            ts_def = await crud_text_splitter.get_default_by_user_id(user_id=current_user.id, db_session=db)
            if ts_def:
                eff_chunk_size = ts_def.chunk_size
                eff_chunk_overlap = ts_def.chunk_overlap
                eff_separators = ts_def.separators
                if eff_splitter_type is None:
                    eff_splitter_type = getattr(ts_def, "splitter_type", None)
                if eff_params is None:
                    eff_params = getattr(ts_def, "params", None)

        ids = await rag.upsert_texts(
            user_id=current_user.id,
            texts=[text],
            provider=provider or doc.embed_provider,
            embed_model=embed_model or doc.embed_model,
            chunk_size=eff_chunk_size,
            chunk_overlap=eff_chunk_overlap,
            separators=eff_separators,
            splitter_type=eff_splitter_type,
            params=eff_params,
            base_metadata={
                "knowledge_id": knowledge_id,
                "user_id": current_user.id,
                "document_id": doc.id,
                "filename": doc.filename,
            },
        )
        updated = await crud_knowledge_document.update(
            obj_current=doc,
            obj_new={"status": "indexed", "vector_ids": ids, "error": None},
            db_session=db,
        )
        return KnowledgeDocumentRead.model_validate(updated, from_attributes=True)
    except ValueError as e:
        updated = await crud_knowledge_document.update(
            obj_current=doc,
            obj_new={"status": "error", "error": repr(e)},
            db_session=db,
        )
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        updated = await crud_knowledge_document.update(
            obj_current=doc,
            obj_new={"status": "error", "error": repr(e)},
            db_session=db,
        )
        raise HTTPException(status_code=500, detail=f"重建索引失败: {repr(e)}")
