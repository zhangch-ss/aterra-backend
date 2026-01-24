from sqlalchemy import select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

class CRUDUserFilterMixin:
    """通用过滤逻辑（user_id, type, scene, keyword）"""

    async def get_by_user_id(
        self,
        user_id: str,
        db_session: AsyncSession,
        with_relations: bool = False,
        type: Optional[str] = None,
        scene: Optional[str] = None,
        keyword: Optional[str] = None,
    ):
        conditions = [self.model.user_id == user_id]

        if type:
            conditions.append(self.model.type == type)
        if scene:
            conditions.append(self.model.scene == scene)
        if keyword:
            conditions.append(
                or_(
                    self.model.name.ilike(f"%{keyword}%"),
                    self.model.description.ilike(f"%{keyword}%"),
                )
            )

        query = select(self.model).where(and_(*conditions))

        # 允许子类控制是否加载关系
        if hasattr(self, "_with_relations") and self._with_relations and with_relations:
            query = query.options(*self._with_relations)

        result = await db_session.execute(query)
        return result.scalars().all()

    async def get_market_list(
        self,
        db_session: AsyncSession,
        with_relations: bool = False,
        type: Optional[str] = None,
        scene: Optional[str] = None,
        keyword: Optional[str] = None,
    ):
        """
        市场资源列表：user_id IS NULL 且（可选）按 type / scene / keyword 过滤
        """
        conditions = [self.model.user_id.is_(None)]

        # 仅当模型包含 is_active 时才过滤
        try:
            is_active_col = getattr(self.model, "is_active")
            conditions.append(is_active_col.is_(True))
        except Exception:
            pass

        if type and hasattr(self.model, "type"):
            conditions.append(self.model.type == type)
        if scene and hasattr(self.model, "scene"):
            conditions.append(self.model.scene == scene)
        if keyword:
            name_col = getattr(self.model, "name", None)
            desc_col = getattr(self.model, "description", None)
            ors = []
            if name_col is not None:
                ors.append(name_col.ilike(f"%{keyword}%"))
            if desc_col is not None:
                ors.append(desc_col.ilike(f"%{keyword}%"))
            if ors:
                conditions.append(or_(*ors))

        query = select(self.model).where(and_(*conditions))

        if hasattr(self, "_with_relations") and self._with_relations and with_relations:
            query = query.options(*self._with_relations)

        result = await db_session.execute(query)
        return result.scalars().all()
