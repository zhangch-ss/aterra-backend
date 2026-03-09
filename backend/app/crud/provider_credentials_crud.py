from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from sqlalchemy import and_
from app.models.provider_credentials import ProviderCredentials


class CRUDProviderCredentials:
    """针对 ProviderCredentials 的简单 CRUD 封装
    以 (user_id, provider) 唯一约束进行查找与更新
    """

    async def get_by_user_provider(
        self, db_session: AsyncSession, user_id: str, provider: str
    ) -> Optional[ProviderCredentials]:
        q = select(ProviderCredentials).where(
            and_(
                ProviderCredentials.user_id == user_id,
                ProviderCredentials.provider == provider,
            )
        )
        res = await db_session.execute(q)
        return res.scalar_one_or_none()

    async def upsert(
        self,
        db_session: AsyncSession,
        user_id: str,
        provider: str,
        values: Dict[str, Any],
    ) -> ProviderCredentials:
        """存在则更新，不存在则创建"""
        existing = await self.get_by_user_provider(db_session, user_id, provider)
        if existing:
            # 仅更新提供的字段
            for k, v in values.items():
                setattr(existing, k, v)
            db_session.add(existing)
            await db_session.commit()
            await db_session.refresh(existing)
            return existing

        obj = ProviderCredentials(user_id=user_id, provider=provider, **values)
        db_session.add(obj)
        await db_session.commit()
        await db_session.refresh(obj)
        return obj

    async def delete_by_user_provider(
        self, db_session: AsyncSession, user_id: str, provider: str
    ) -> None:
        existing = await self.get_by_user_provider(db_session, user_id, provider)
        if existing:
            await db_session.delete(existing)
            await db_session.commit()


# ✅ 单例实例
crud_provider_credentials = CRUDProviderCredentials()
