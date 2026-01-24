from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_
from app.models.model import Model
from app.schemas.model import ModelCreateInput, ModelUpdate
from app.crud.base_crud import CRUDBase


class CRUDModel(CRUDBase[Model, ModelCreateInput, ModelUpdate]):
    """Model registry CRUD.
    Supports filtering by provider and keyword for the owning user.
    """
    def __init__(self):
        super().__init__(Model)

    async def get_by_user_id(
        self,
        user_id: str,
        db_session: AsyncSession,
        provider: Optional[str] = None,
        keyword: Optional[str] = None,
    ) -> list[Model]:
        conditions = [Model.user_id == user_id]
        if provider:
            conditions.append(Model.provider == provider)
        if keyword:
            conditions.append(
                or_(
                    Model.name.ilike(f"%{keyword}%"),
                    Model.description.ilike(f"%{keyword}%"),
                )
            )
        query = select(Model).where(and_(*conditions))
        result = await db_session.execute(query)
        return result.scalars().all()


# ✅ 单例实例
crud_model = CRUDModel()
