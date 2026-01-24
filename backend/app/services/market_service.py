from typing import Optional, Dict, Any, List
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
import json

from app.schemas.market import CopyMode
from app.crud.agent_crud import crud_agent
from app.crud.knowledge_crud import crud_knowledge
from app.crud.tool_crud import crud_tool
from app.crud.prompt_crud import crud_prompt


class MarketService:
    """
    市场服务：
    - list_market：列出市场资源（user_id IS NULL）
    - copy_to_user：将市场资源复制到指定用户（shallow）
    - publish_to_market：将用户资源发布为市场副本（user_id=None）
    - unpublish_market：下架市场资源（软下架 is_active=False）
    """
    def __init__(self):
        # 资源类型映射到 CRUD 单例
        self.crud_map = {
            "agents": crud_agent,
            "knowledges": crud_knowledge,
            "tools": crud_tool,
            "prompts": crud_prompt,
        }

    def _get_crud(self, resource: str):
        crud = self.crud_map.get(resource)
        if not crud:
            raise HTTPException(status_code=400, detail=f"不支持的资源类型: {resource}")
        return crud

    def _get_allowed_columns(self, model: Any) -> set[str]:
        try:
            return set(model.__table__.columns.keys())
        except Exception:
            return set()

    def _normalize_value(self, value: Any) -> Any:
        # 归一化 Enum / JSON / 复杂对象，确保可比较
        if hasattr(value, "value"):
            try:
                return getattr(value, "value")
            except Exception:
                pass
        if isinstance(value, (dict, list)):
            try:
                return json.dumps(value, sort_keys=True, ensure_ascii=False)
            except Exception:
                return str(value)
        return value

    def _fingerprint(self, obj: Any, model: Any) -> tuple:
        """
        基于“可复制字段”的值生成稳定指纹（用于判定是否已添加到工作台）。
        - 排除：id/时间戳/审计/is_active/user_id
        """
        allowed_columns = self._get_allowed_columns(model)
        exclude_fields = {"id", "created_at", "updated_at", "created_by_id", "updated_by_id", "is_active", "user_id"}
        items: list[tuple[str, Any]] = []
        for col in allowed_columns:
            if col in exclude_fields:
                continue
            val = getattr(obj, col, None)
            items.append((col, self._normalize_value(val)))
        # 排序后转为 tuple 作为可哈希的签名
        items.sort(key=lambda x: x[0])
        return tuple(items)

    async def _build_user_fingerprint_map(self, crud, *, user_id: str, db_session: AsyncSession) -> Dict[tuple, Any]:
        """
        获取用户当前资源集合，并构建 指纹->对象 的映射。
        """
        user_items = await crud.get_by_user_id(user_id=user_id, db_session=db_session)
        fp_map: Dict[tuple, Any] = {}
        if not user_items:
            return fp_map
        for it in user_items:
            fp = self._fingerprint(it, crud.model)
            # 仅保留首个匹配对象（足以用于已存在判断）
            if fp not in fp_map:
                fp_map[fp] = it
        return fp_map

    async def get_is_added_map(
        self,
        *,
        resource: str,
        items: List[Any],
        user_id: Optional[str],
        db_session: AsyncSession,
    ) -> Dict[str, bool]:
        """
        对市场 items 计算是否已被指定用户添加（同内容判重）。
        返回字典：{market_item.id: bool}
        """
        if not user_id or not items:
            return {getattr(it, "id", ""): False for it in items}
        crud = self._get_crud(resource)
        user_fp_map = await self._build_user_fingerprint_map(crud, user_id=user_id, db_session=db_session)
        result: Dict[str, bool] = {}
        for it in items:
            fp = self._fingerprint(it, crud.model)
            result[getattr(it, "id", "")] = fp in user_fp_map
        return result

    async def find_user_existing_copy(
        self,
        *,
        resource: str,
        market_obj: Any,
        target_user_id: str,
        db_session: AsyncSession,
    ) -> Any | None:
        """
        查找与市场对象“相同内容”的用户侧副本，存在则返回该对象。
        """
        crud = self._get_crud(resource)
        user_fp_map = await self._build_user_fingerprint_map(crud, user_id=target_user_id, db_session=db_session)
        fp = self._fingerprint(market_obj, crud.model)
        return user_fp_map.get(fp)

    async def list_market(
        self,
        *,
        resource: str,
        db_session: AsyncSession,
        with_relations: bool = False,
        type: Optional[str] = None,
        scene: Optional[str] = None,
        keyword: Optional[str] = None,
    ) -> List[Any]:
        crud = self._get_crud(resource)
        # 统一调用 mixin 的 get_market_list
        items = await crud.get_market_list(
            db_session=db_session,
            with_relations=with_relations,
            type=type,
            scene=scene,
            keyword=keyword,
        )
        return items

    def _extract_create_data(self, obj: Any, model: Any, *, target_user_id: Optional[str]) -> Dict[str, Any]:
        """
        从已有对象提取可创建字段，排除 id/时间戳/审计/is_active，并覆盖 user_id。
        """
        data: Dict[str, Any] = {}
        # 允许列集合
        try:
            allowed_columns = set(model.__table__.columns.keys())
        except Exception:
            allowed_columns = set()

        # 不复制的列
        exclude_fields = {"id", "created_at", "updated_at", "created_by_id", "updated_by_id", "is_active"}

        for col in allowed_columns:
            if col in exclude_fields:
                continue
            # 复制现有值
            value = getattr(obj, col, None)
            data[col] = value

        # 覆盖 user_id
        if "user_id" in allowed_columns:
            data["user_id"] = target_user_id

        return data

    async def copy_to_user(
        self,
        *,
        resource: str,
        id: str,
        target_user_id: str,
        db_session: AsyncSession,
        copy_mode: CopyMode = CopyMode.shallow,
    ) -> Any:
        """
        将市场资源（user_id=None）复制到用户工作台（user_id=target_user_id）。
        - 幂等校验：若该用户已存在“同内容副本”，则阻止重复添加（409）。
        当前版本实现 shallow：仅复制本体，不复制关系。
        """
        crud = self._get_crud(resource)
        obj = await crud.get(id=id, db_session=db_session)
        if not obj:
            raise HTTPException(status_code=404, detail="市场资源不存在")
        # 必须为市场资源
        if getattr(obj, "user_id", None) is not None:
            raise HTTPException(status_code=400, detail="该资源不是市场资源（user_id 不为空）")

        # 幂等：判断该用户是否已存在“同内容”的副本
        existing = await self.find_user_existing_copy(
            resource=resource,
            market_obj=obj,
            target_user_id=target_user_id,
            db_session=db_session,
        )
        if existing:
            # 明确告知前端：已添加到工作台
            raise HTTPException(status_code=409, detail="该资源已添加到工作台，不能重复添加")

        data = self._extract_create_data(obj, crud.model, target_user_id=target_user_id)

        # 创建新对象（使用模型实例或字典均可，这里用字典）
        new_obj = crud.model.model_validate(data)  # type: ignore
        created = await crud.create(obj_in=new_obj, created_by_id=target_user_id, db_session=db_session)
        return created

    async def publish_to_market(
        self,
        *,
        resource: str,
        id: str,
        db_session: AsyncSession,
        copy_deps: bool = False,
    ) -> Any:
        """
        将用户资源发布为市场副本（user_id=None）。
        当前版本不复制关系（copy_deps 暂不使用）。
        """
        crud = self._get_crud(resource)
        obj = await crud.get(id=id, db_session=db_session)
        if not obj:
            raise HTTPException(status_code=404, detail="资源不存在")
        # 必须为用户资源
        if getattr(obj, "user_id", None) is None:
            raise HTTPException(status_code=400, detail="该资源已是市场资源（user_id 为空）")

        data = self._extract_create_data(obj, crud.model, target_user_id=None)

        new_obj = crud.model.model_validate(data)  # type: ignore
        created = await crud.create(obj_in=new_obj, db_session=db_session)
        return created

    async def unpublish_market(
        self,
        *,
        resource: str,
        id: str,
        db_session: AsyncSession,
    ) -> dict:
        """
        下架市场资源：is_active=False（软下架）。
        """
        crud = self._get_crud(resource)
        obj = await crud.get(id=id, db_session=db_session)
        if not obj:
            raise HTTPException(status_code=404, detail="资源不存在")
        # 必须为市场资源
        if getattr(obj, "user_id", None) is not None:
            raise HTTPException(status_code=400, detail="不能下架用户私有资源")

        # 软下架
        updated = await crud.update(obj_current=obj, obj_new={"is_active": False}, db_session=db_session)
        return {"ok": True, "id": updated.id}


# 单例
market_service = MarketService()
