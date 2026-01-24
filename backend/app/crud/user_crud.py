from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException
from typing import Optional

from app.models.user import User
from app.crud.base_crud import CRUDBase
from app.schemas.user import UserCreate, UserUpdate
from app.core.security import get_password_hash, verify_password


class CRUDUser(CRUDBase[User, UserCreate, UserUpdate]):
    def __init__(self):
        super().__init__(User)

    async def get_by_username(self, *, username: str, db_session: AsyncSession | None = None) -> Optional[User]:
        db_session = db_session or self.db.session
        result = await db_session.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

    async def get_by_email(self, *, email: str, db_session: AsyncSession | None = None) -> Optional[User]:
        db_session = db_session or self.db.session
        result = await db_session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def create_user(self, *, obj_in: UserCreate, db_session: AsyncSession | None = None) -> User:
        db_session = db_session or self.db.session
        hashed_password = get_password_hash(obj_in.password)
        db_obj = User(
            username=obj_in.username,
            email=obj_in.email,
            full_name=obj_in.full_name,
            hashed_password=hashed_password,
            role=obj_in.role,
            is_superuser=obj_in.is_superuser,
            organization=obj_in.organization,
            avatar_url=obj_in.avatar_url,
        )
        try:
            db_session.add(db_obj)
            await db_session.commit()
            await db_session.refresh(db_obj)
            return db_obj
        except Exception as e:
            await db_session.rollback()
            raise HTTPException(status_code=400, detail=f"Could not create user: {e}")

    async def authenticate(self, *, username: str, password: str, db_session: AsyncSession | None = None) -> Optional[User]:
        db_session = db_session or self.db.session
        user = await self.get_by_username(username=username, db_session=db_session)
        if not user:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user


crud_user = CRUDUser()
