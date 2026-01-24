from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.text_splitter import TextSplitter
from app.schemas.text_splitter import (
    TextSplitterCreateInput,
    TextSplitterUpdate,
    TextSplitterRead,
    TextSplitterCardOut,
)
from app.crud.text_splitter_crud import crud_text_splitter

router = APIRouter()


@router.post("/create", response_model=TextSplitterRead)
async def create_text_splitter(
    payload: TextSplitterCreateInput,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    obj = TextSplitter(**payload.dict(), user_id=current_user.id)
    created = await crud_text_splitter.create(obj_in=obj, created_by_id=current_user.id, db_session=db)
    return TextSplitterRead.model_validate(created, from_attributes=True)


@router.put("/{splitter_id}", response_model=TextSplitterRead)
async def update_text_splitter(
    splitter_id: str,
    payload: TextSplitterUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ts = await crud_text_splitter.get(id=splitter_id, db_session=db)
    if not ts:
        raise HTTPException(status_code=404, detail="切片器不存在")
    if ts.user_id != current_user.id and not getattr(current_user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="无权限修改该切片器")

    updated = await crud_text_splitter.update(obj_current=ts, obj_new=payload, db_session=db)
    return TextSplitterRead.model_validate(updated, from_attributes=True)


@router.delete("/{splitter_id}", response_model=dict)
async def delete_text_splitter(
    splitter_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ts = await crud_text_splitter.get(id=splitter_id, db_session=db)
    if not ts:
        raise HTTPException(status_code=404, detail="切片器不存在")
    if ts.user_id != current_user.id and not getattr(current_user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="无权限删除该切片器")

    await crud_text_splitter.remove(id=splitter_id, db_session=db)
    return {"ok": True}


@router.get("/list", response_model=List[TextSplitterRead])
async def list_text_splitters(
    keyword: Optional[str] = None,
    skip: int = 0,
    limit: int = Query(100, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items = await crud_text_splitter.get_by_user_id(
        user_id=current_user.id, db_session=db, keyword=keyword, skip=skip, limit=limit
    )
    return [TextSplitterRead.model_validate(i, from_attributes=True) for i in items]


@router.get("/{splitter_id}", response_model=TextSplitterRead)
async def get_text_splitter(
    splitter_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ts = await crud_text_splitter.get(id=splitter_id, db_session=db)
    if not ts:
        raise HTTPException(status_code=404, detail="切片器不存在")
    if ts.user_id != current_user.id and not getattr(current_user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="无权限查看该切片器")
    return TextSplitterRead.model_validate(ts, from_attributes=True)


@router.post("/{splitter_id}/set_default", response_model=TextSplitterRead)
async def set_default_text_splitter(
    splitter_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ts = await crud_text_splitter.set_default(id=splitter_id, user_id=current_user.id, db_session=db)
    return TextSplitterRead.model_validate(ts, from_attributes=True)


@router.get("/default", response_model=TextSplitterRead)
async def get_default_text_splitter(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ts = await crud_text_splitter.get_default_by_user_id(user_id=current_user.id, db_session=db)
    if not ts:
        raise HTTPException(status_code=404, detail="默认切片器不存在")
    return TextSplitterRead.model_validate(ts, from_attributes=True)
