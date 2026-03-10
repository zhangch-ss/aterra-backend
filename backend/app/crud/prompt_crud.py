from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from sqlalchemy import and_, or_
from app.crud.base_crud import CRUDBase
from app.crud.mixins import CRUDUserFilterMixin
from app.models.prompt import Prompt
from app.schemas.prompt import PromptCreate, PromptUpdate
from app.schemas.common import IOrderEnum
from typing import Optional, List

class CRUDPrompt(CRUDBase[Prompt, PromptCreate, PromptUpdate], CRUDUserFilterMixin):
    """📝 Prompt CRUD
    - 继承通用 CRUDBase 提供 create/get/update/remove
    - 继承用户过滤 Mixins，支持按 user_id/type/scene/keyword 查询
    """

    def __init__(self):
        super().__init__(Prompt)

    async def get_by_name(
        self,
        *,
        user_id: str,
        name: str,
        db_session: AsyncSession,
    ) -> Optional[Prompt]:
        result = await db_session.execute(
            select(Prompt).where(and_(Prompt.user_id == user_id, Prompt.name == name))
        )
        return result.scalar_one_or_none()

    async def get_system_prompt_by_name(
        self,
        *,
        name: str,
        db_session: AsyncSession,
    ) -> Optional[Prompt]:
        result = await db_session.execute(
            select(Prompt).where(and_(Prompt.visibility == "system", Prompt.name == name))
        )
        return result.scalar_one_or_none()

    async def search(
        self,
        *,
        user_id: str,
        role: Optional[str] = None,
        scene: Optional[str] = None,
        keyword: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        order_by: Optional[str] = None,
        order: IOrderEnum = IOrderEnum.ascendent,
        db_session: AsyncSession,
    ) -> List[Prompt]:
        conditions = [Prompt.user_id == user_id]
        if role:
            conditions.append(Prompt.role == role)
        if scene:
            conditions.append(Prompt.scene == scene)
        if keyword:
            like = f"%{keyword}%"
            conditions.append(
                or_(Prompt.name.ilike(like), Prompt.description.ilike(like), Prompt.content.ilike(like))
            )

        # 排序与分页
        columns = Prompt.__table__.columns
        if order_by is None or order_by not in columns:
            order_by = "updated_at"
        order_clause = columns[order_by].asc() if order == IOrderEnum.ascendent else columns[order_by].desc()

        offset = max(page - 1, 0) * max(page_size, 1)
        limit = max(page_size, 1)

        query = (
            select(Prompt)
            .where(and_(*conditions))
            .order_by(order_clause)
            .offset(offset)
            .limit(limit)
        )
        result = await db_session.execute(query)
        return result.scalars().all()


# ✅ 单例
crud_prompt = CRUDPrompt()
