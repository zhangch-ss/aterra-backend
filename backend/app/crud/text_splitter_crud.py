from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_, update
from fastapi import HTTPException
from app.models.text_splitter import TextSplitter
from app.schemas.text_splitter import TextSplitterCreateInput, TextSplitterUpdate
from app.crud.base_crud import CRUDBase


class CRUDTextSplitter(CRUDBase[TextSplitter, TextSplitterCreateInput, TextSplitterUpdate]):
    """TextSplitter 配置的 CRUD。
    - 支持按用户与关键词过滤
    - 支持设置/获取用户默认切片器
    """
    def __init__(self):
        super().__init__(TextSplitter)

    async def get_by_user_id(
        self,
        user_id: str,
        db_session: AsyncSession,
        keyword: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[TextSplitter]:
        conditions = [TextSplitter.user_id == user_id]
        if keyword:
            conditions.append(
                or_(
                    TextSplitter.name.ilike(f"%{keyword}%"),
                    TextSplitter.description.ilike(f"%{keyword}%"),
                )
            )
        query = select(TextSplitter).where(and_(*conditions)).offset(skip).limit(limit)
        result = await db_session.execute(query)
        return result.scalars().all()

    async def get_default_by_user_id(
        self,
        user_id: str,
        db_session: AsyncSession,
    ) -> TextSplitter | None:
        query = select(TextSplitter).where(
            and_(TextSplitter.user_id == user_id, TextSplitter.is_default == True)
        )
        result = await db_session.execute(query)
        return result.scalar_one_or_none()

    async def set_default(
        self,
        *,
        id: str,
        user_id: str,
        db_session: AsyncSession,
    ) -> TextSplitter:
        ts = await self.get(id=id, db_session=db_session)
        if not ts:
            raise HTTPException(status_code=404, detail="切片器不存在")
        if ts.user_id != user_id:
            raise HTTPException(status_code=403, detail="无权限设置该切片器为默认")

        # 取消该用户下其他默认
        await db_session.execute(
            update(TextSplitter)
            .where(and_(TextSplitter.user_id == user_id, TextSplitter.is_default == True))
            .values(is_default=False)
        )

        # 设置当前为默认
        ts.is_default = True
        db_session.add(ts)
        await db_session.commit()
        await db_session.refresh(ts)
        return ts


# ✅ 单例实例
crud_text_splitter = CRUDTextSplitter()
