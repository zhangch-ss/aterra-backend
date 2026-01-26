from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.db.session import SessionLocal, SessionLocalCelery
from app.crud.user_crud import crud_user
from app.core.security import decode_token
from app.utils.token_store import get_redis_client, is_token_revoked


reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login/access-token",
    auto_error=False,  # allow bypass in local mode when no token provided
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def get_jobs_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocalCelery() as session:
        yield session


async def get_current_user(
    token: str | None = Depends(reusable_oauth2),
    db: AsyncSession = Depends(get_db),
):
    """Extract current user.
    - In local dev bypass mode, return a local debug user (auto-create if missing).
    - Otherwise, validate bearer token and load user from DB.
    """
    # Local bypass: only active when explicitly enabled and in development mode
    from app.core.config import ModeEnum
    if getattr(settings, "AUTH_LOCAL_MODE", False) and settings.MODE == ModeEnum.development:
        # Attempt to find or create a local user
        username = settings.AUTH_LOCAL_USERNAME or "local"
        email = settings.AUTH_LOCAL_EMAIL or "local@example.com"
        is_super = bool(getattr(settings, "AUTH_LOCAL_IS_SUPERUSER", True))
        user = await crud_user.get_by_username(username=username, db_session=db)
        if not user:
            # create a simple local user with default password 'local'
            try:
                from app.schemas.user import UserCreate
                user = await crud_user.create_user(
                    obj_in=UserCreate(
                        username=username,
                        password="local",
                        email=email,
                        full_name="Local Debug User",
                        is_superuser=is_super,
                        role="admin" if is_super else "user",
                    ),
                    db_session=db,
                )
            except Exception:
                # In case of race condition unique constraint, fetch again
                user = await crud_user.get_by_username(username=username, db_session=db)
        return user

    # Normal flow: token required
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user_id = payload.get("sub")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Revocation check (blacklist)
    redis = get_redis_client()
    if await is_token_revoked(redis, user_id, token):
        raise HTTPException(status_code=401, detail="Token has been revoked")

    user = await crud_user.get(id=user_id, db_session=db)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user
