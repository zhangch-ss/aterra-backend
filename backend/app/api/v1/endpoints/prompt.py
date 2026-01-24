from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, get_current_user
from app.crud.prompt_crud import crud_prompt
from app.schemas.prompt import PromptCreate, PromptUpdate, PromptRead
from app.models.user import User
from app.models.prompt import Prompt
from app.schemas.common import IOrderEnum

router = APIRouter()

# 创建 Prompt
@router.post("/create", response_model=PromptRead)
async def create_prompt(
    payload: PromptCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 从鉴权上下文自动注入 user_id
    obj = Prompt(**payload.dict(), user_id=current_user.id)
    prompt = await crud_prompt.create(obj_in=obj, db_session=db)
    return prompt

# 更新 Prompt
@router.put("/{prompt_id}", response_model=PromptRead)
async def update_prompt(
    prompt_id: str,
    payload: PromptUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    prompt = await crud_prompt.get(id=prompt_id, db_session=db)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt 不存在")
    # 权限校验：只能修改自己的 Prompt，管理员除外
    if prompt.user_id != current_user.id and not getattr(current_user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="无权限修改该 Prompt")
    updated = await crud_prompt.update(obj_current=prompt, obj_new=payload, db_session=db)
    return updated

# 删除 Prompt
@router.delete("/{prompt_id}")
async def delete_prompt(
    prompt_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    prompt = await crud_prompt.get(id=prompt_id, db_session=db)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt 不存在")
    # 权限校验：只能删除自己的 Prompt，管理员除外
    if prompt.user_id != current_user.id and not getattr(current_user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="无权限删除该 Prompt")
    await crud_prompt.remove(id=prompt_id, db_session=db)
    return {"message": "删除成功"}

# 获取某用户的 Prompt 列表（支持过滤）
@router.get("/list", response_model=list[PromptRead])
async def list_prompts(
    role: str | None = None,
    scene: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
    order_by: str | None = None,
    order: IOrderEnum = IOrderEnum.ascendent,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    prompts = await crud_prompt.search(
        user_id=current_user.id,
        role=role,
        scene=scene,
        keyword=keyword,
        page=page,
        page_size=page_size,
        order_by=order_by,
        order=order,
        db_session=db,
    )
    return prompts

# 兼容旧路径：/list_prompts
@router.get("/list_prompts", response_model=list[PromptRead])
async def list_prompts_alias(
    role: str | None = None,
    scene: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
    order_by: str | None = None,
    order: IOrderEnum = IOrderEnum.ascendent,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    prompts = await crud_prompt.search(
        user_id=current_user.id,
        role=role,
        scene=scene,
        keyword=keyword,
        page=page,
        page_size=page_size,
        order_by=order_by,
        order=order,
        db_session=db,
    )
    return prompts

# 提示词类型枚举（兼容旧接口）
@router.get("/prompt_type", response_model=list[str])
async def prompt_type():
    """返回内置的提示词角色类型列表。"""
    return [
        "system",
        "user",
        "assistant",
        "tool",
        "template",
    ]

# 获取单个 Prompt
@router.get("/{prompt_id}", response_model=PromptRead)
async def get_prompt(
    prompt_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    prompt = await crud_prompt.get(id=prompt_id, db_session=db)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt 不存在")
    # 权限校验：只能查看自己的 Prompt，管理员除外
    if prompt.user_id != current_user.id and not getattr(current_user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="无权限查看该 Prompt")
    return prompt
