from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.market import ResourceType, MarketAddRequest, MarketPublishRequest
from app.services.market_service import market_service

# 可复用的 Read/Card Schema（用于 add-to-workspace 成功后的返回）
from app.schemas.agent import AgentRead
from app.schemas.knowledge import KnowledgeRead, KnowledgeCardOut
from app.schemas.tool import CreateToolCardOut
from app.schemas.prompt import PromptRead

router = APIRouter()


def _to_card(resource: ResourceType, obj: Any) -> Dict[str, Any]:
    """
    将不同资源类型统一映射为前端卡片结构（避免 user_id=None 的校验问题）。
    - agents: id, name, desc, type, scene
    - knowledges: id, name, description
    - tools: id, name, description, type
    - prompts: id, name, description, role, scene, version
    """
    if resource == ResourceType.agents:
        return {
            "id": obj.id,
            "name": obj.name,
            "desc": getattr(obj, "description", None),
            "type": getattr(obj, "type", None),
            "scene": getattr(obj, "scene", None),
        }
    elif resource == ResourceType.knowledges:
        return {
            "id": obj.id,
            "name": obj.name,
            "description": getattr(obj, "description", None),
        }
    elif resource == ResourceType.tools:
        t = getattr(obj, "type", None)
        t_val = t.value if hasattr(t, "value") else t
        return {
            "id": obj.id,
            "name": obj.name,
            "description": getattr(obj, "description", None),
            "type": t_val,
        }
    elif resource == ResourceType.prompts:
        return {
            "id": obj.id,
            "name": obj.name,
            "description": getattr(obj, "description", None),
            "role": getattr(obj, "role", None),
            "scene": getattr(obj, "scene", None),
            "version": getattr(obj, "version", None),
        }
    else:
        return {"id": getattr(obj, "id", None), "name": getattr(obj, "name", None)}


@router.get("/{resource}")
async def list_market_resources(
    resource: ResourceType,
    type: Optional[str] = None,
    scene: Optional[str] = None,
    keyword: Optional[str] = None,
    user_id: Optional[str] = None,
    with_relations: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """
    市场资源列表（user_id IS NULL + is_active=True）
    返回轻量卡片结构，避免 user_id=None 的 Pydantic 校验问题。
    """
    items = await market_service.list_market(
        resource=resource.value,
        db_session=db,
        with_relations=with_relations,
        type=type,
        scene=scene,
        keyword=keyword,
    )
    # 基于当前用户，标注市场条目是否已添加到工作台
    is_added_map = await market_service.get_is_added_map(
        resource=resource.value,
        items=items,
        user_id=user_id,
        db_session=db,
    )
    result = []
    for it in items:
        card = _to_card(resource, it)
        card["is_added"] = is_added_map.get(getattr(it, "id", ""), False)
        result.append(card)
    return result


@router.post("/{resource}/{item_id}/add-to-workspace")
async def add_to_workspace(
    resource: ResourceType,
    item_id: str,
    payload: MarketAddRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    将市场资源复制到用户工作台（shallow）。
    - 有些 Read 模型要求 user_id 为字符串，因此复制成功后可以安全使用对应 Read 模型返回。
    """
    created = await market_service.copy_to_user(
        resource=resource.value,
        id=item_id,
        target_user_id=payload.user_id,
        db_session=db,
        copy_mode=payload.copy_mode,
    )

    # 针对不同资源返回更友好的结构/Schema
    if resource == ResourceType.agents:
        return AgentRead.model_validate(created, from_attributes=True)
    if resource == ResourceType.knowledges:
        return KnowledgeRead.model_validate(created, from_attributes=True)
    if resource == ResourceType.tools:
        return CreateToolCardOut.model_validate(created, from_attributes=True)
    if resource == ResourceType.prompts:
        return PromptRead.model_validate(created, from_attributes=True)

    return created


@router.post("/{resource}/{item_id}/publish")
async def publish_to_market(
    resource: ResourceType,
    item_id: str,
    payload: MarketPublishRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    将用户资源发布为市场（拷贝为 user_id=None 的市场副本）。
    返回 id/ok，避免 user_id=None 的验证问题。
    """
    created = await market_service.publish_to_market(
        resource=resource.value,
        id=item_id,
        db_session=db,
        copy_deps=payload.copy_deps or False,
    )
    return {"ok": True, "id": getattr(created, "id", None)}


@router.post("/{resource}/{item_id}/unpublish")
async def unpublish_market(
    resource: ResourceType,
    item_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    下架市场资源（is_active=False）。仅对 user_id=None 的资源生效。
    """
    result = await market_service.unpublish_market(
        resource=resource.value,
        id=item_id,
        db_session=db,
    )
    return result
