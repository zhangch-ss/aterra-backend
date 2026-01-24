from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import get_db, reusable_oauth2, get_current_user
from app.crud.user_crud import crud_user
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.schemas.user import (
    Token,
    TokenPair,
    UserCreate,
    UserRead,
    RefreshTokenRequest,
    LogoutRequest,
)
from app.utils.token_store import (
    get_redis_client,
    revoke_token,
    store_refresh_token,
    is_refresh_token_valid,
    revoke_refresh_token,
    revoke_all_refresh_tokens,
    store_access_refresh_pair,
    get_refresh_by_access,
    delete_access_refresh_pair,
)
from app.core.config import settings

router = APIRouter()


@router.post("/login/access-token", response_model=TokenPair)
async def login_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    user = await crud_user.authenticate(
        username=form_data.username, password=form_data.password, db_session=db
    )
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect username or password")

    access_token = create_access_token(subject=user.id)
    refresh_token = create_refresh_token(subject=user.id)

    redis = get_redis_client()
    await store_refresh_token(
        redis_client=redis,
        user_id=user.id,
        refresh_token=refresh_token,
        expire_minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES,
    )
    # map current access -> refresh for logout revoke
    await store_access_refresh_pair(
        redis_client=redis,
        user_id=user.id,
        access_token=access_token,
        refresh_token=refresh_token,
        access_expire_minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES,
    )
    return TokenPair(access_token=access_token, refresh_token=refresh_token)


@router.post("/login/refresh", response_model=TokenPair)
async def refresh_access_token(payload: RefreshTokenRequest):
    """Exchange a valid refresh token for a new access token and rotated refresh token."""
    # Decode and validate token type
    try:
        data = decode_token(payload.refresh_token)
        if data.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user_id = data.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token payload")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    # Validate token against allowlist
    redis = get_redis_client()
    if not await is_refresh_token_valid(redis, user_id, payload.refresh_token):
        raise HTTPException(status_code=401, detail="Refresh token is not valid or has been revoked")

    # Rotate refresh token
    await revoke_refresh_token(redis, user_id, payload.refresh_token)
    new_refresh = create_refresh_token(subject=user_id)
    await store_refresh_token(
        redis_client=redis,
        user_id=user_id,
        refresh_token=new_refresh,
        expire_minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES,
    )

    # Issue new access token
    new_access = create_access_token(subject=user_id)

    # map new access -> new refresh
    await store_access_refresh_pair(
        redis_client=redis,
        user_id=user_id,
        access_token=new_access,
        refresh_token=new_refresh,
        access_expire_minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES,
    )

    return TokenPair(access_token=new_access, refresh_token=new_refresh)


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register_user(payload: UserCreate, db: AsyncSession = Depends(get_db)):
    # Check unique constraints
    if await crud_user.get_by_username(username=payload.username, db_session=db):
        raise HTTPException(status_code=409, detail="Username already exists")
    if payload.email and await crud_user.get_by_email(email=payload.email, db_session=db):
        raise HTTPException(status_code=409, detail="Email already exists")

    user = await crud_user.create_user(obj_in=payload, db_session=db)
    return UserRead(
        id=user.id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        organization=user.organization,
        avatar_url=user.avatar_url,
        role=user.role,
        is_superuser=user.is_superuser,
    )


@router.get("/me", response_model=UserRead)
async def read_users_me(token: str = Depends(reusable_oauth2), db: AsyncSession = Depends(get_db)):
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user_id = payload.get("sub")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = await crud_user.get(id=user_id, db_session=db)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return UserRead(
        id=user.id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        organization=user.organization,
        avatar_url=user.avatar_url,
        role=user.role,
        is_superuser=user.is_superuser,
    )


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(
    token: str = Depends(reusable_oauth2),
    current_user = Depends(get_current_user),
    payload: LogoutRequest | None = None,
):
    """Revoke current access token; optionally revoke its paired refresh token for current device."""
    redis = get_redis_client()
    # Revoke current access token until it naturally expires
    await revoke_token(redis, current_user.id, token, expire_minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    # If requested, revoke the refresh token paired with this access
    if payload and payload.revoke_refresh:
        try:
            mapped_refresh = await get_refresh_by_access(redis, current_user.id, token)
            if mapped_refresh:
                await revoke_refresh_token(redis, current_user.id, mapped_refresh)
        except Exception:
            pass
    # Always cleanup mapping for this access
    try:
        await delete_access_refresh_pair(redis, current_user.id, token)
    except Exception:
        pass

    return {"detail": "Logged out successfully"}


@router.post("/logout/all", status_code=status.HTTP_200_OK)
async def logout_all_devices(current_user = Depends(get_current_user)):
    """Revoke all refresh tokens for the current user (logout all devices)."""
    redis = get_redis_client()
    await revoke_all_refresh_tokens(redis, current_user.id)
    return {"detail": "Logged out from all devices"}
