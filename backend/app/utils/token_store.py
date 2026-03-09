from datetime import timedelta
from typing import Optional
from redis.asyncio import Redis

from app.core.config import settings


# Key patterns (per-token storage to avoid shared TTL across a set)
ACCESS_REVOKED_KEY = "user:{user_id}:revoked:{token}"
REFRESH_VALID_KEY = "user:{user_id}:refresh:valid:{refresh_token}"
REFRESH_REVOKED_KEY = "user:{user_id}:refresh:revoked:{refresh_token}"
# An index set to enumerate valid refresh tokens per user (for logout-all)
REFRESH_VALID_INDEX = "user:{user_id}:refresh:valid:index"
ACCESS_REFRESH_PAIR = "user:{user_id}:pair:{access_token}"


def get_redis_client() -> Redis:
    return Redis(host=settings.REDIS_HOST, port=int(settings.REDIS_PORT), decode_responses=True)


# Access token revocation (blacklist) — store each token as its own key with TTL
async def revoke_token(
    redis_client: Redis,
    user_id: str,
    token: str,
    expire_minutes: Optional[int] = None,
) -> None:
    key = ACCESS_REVOKED_KEY.format(user_id=user_id, token=token)
    # Use setex-like semantics via set + expire
    await redis_client.set(key, 1)
    if expire_minutes:
        await redis_client.expire(key, int(expire_minutes * 60))


async def is_token_revoked(redis_client: Redis, user_id: str, token: str) -> bool:
    key = ACCESS_REVOKED_KEY.format(user_id=user_id, token=token)
    return bool(await redis_client.exists(key))


# Refresh token allowlist and revocation — per-token keys + index set
async def store_refresh_token(
    redis_client: Redis,
    user_id: str,
    refresh_token: str,
    expire_minutes: Optional[int] = None,
) -> None:
    key = REFRESH_VALID_KEY.format(user_id=user_id, refresh_token=refresh_token)
    await redis_client.set(key, 1)
    if expire_minutes:
        await redis_client.expire(key, int(expire_minutes * 60))
    # Track in index for bulk operations
    index_key = REFRESH_VALID_INDEX.format(user_id=user_id)
    await redis_client.sadd(index_key, refresh_token)


async def is_refresh_token_valid(redis_client: Redis, user_id: str, refresh_token: str) -> bool:
    key = REFRESH_VALID_KEY.format(user_id=user_id, refresh_token=refresh_token)
    return bool(await redis_client.exists(key))


async def revoke_refresh_token(
    redis_client: Redis,
    user_id: str,
    refresh_token: str,
) -> None:
    # Delete valid marker, add revoked marker (helpful for auditing)
    valid_key = REFRESH_VALID_KEY.format(user_id=user_id, refresh_token=refresh_token)
    revoked_key = REFRESH_REVOKED_KEY.format(user_id=user_id, refresh_token=refresh_token)
    index_key = REFRESH_VALID_INDEX.format(user_id=user_id)
    async with redis_client.pipeline(transaction=True) as pipe:
        await pipe.delete(valid_key)
        await pipe.srem(index_key, refresh_token)
        await pipe.set(revoked_key, 1)
        # Set TTL for revoked marker to the default refresh lifetime to avoid leak
        await pipe.expire(revoked_key, int(settings.REFRESH_TOKEN_EXPIRE_MINUTES * 60))
        await pipe.execute()


async def store_access_refresh_pair(
    redis_client: Redis,
    user_id: str,
    access_token: str,
    refresh_token: str,
    access_expire_minutes: Optional[int] = None,
) -> None:
    key = ACCESS_REFRESH_PAIR.format(user_id=user_id, access_token=access_token)
    await redis_client.set(key, refresh_token)
    if access_expire_minutes:
        await redis_client.expire(key, int(access_expire_minutes * 60))


async def get_refresh_by_access(
    redis_client: Redis,
    user_id: str,
    access_token: str,
) -> Optional[str]:
    key = ACCESS_REFRESH_PAIR.format(user_id=user_id, access_token=access_token)
    return await redis_client.get(key)


async def delete_access_refresh_pair(
    redis_client: Redis,
    user_id: str,
    access_token: str,
) -> None:
    key = ACCESS_REFRESH_PAIR.format(user_id=user_id, access_token=access_token)
    await redis_client.delete(key)


async def revoke_all_refresh_tokens(redis_client: Redis, user_id: str) -> None:
    """Revoke all refresh tokens for a user.
    Iterates over the index of valid refresh tokens to mark them revoked and remove validity markers.
    """
    index_key = REFRESH_VALID_INDEX.format(user_id=user_id)
    members = await redis_client.smembers(index_key)
    if not members:
        return
    async with redis_client.pipeline(transaction=True) as pipe:
        for token in members:
            valid_key = REFRESH_VALID_KEY.format(user_id=user_id, refresh_token=token)
            revoked_key = REFRESH_REVOKED_KEY.format(user_id=user_id, refresh_token=token)
            await pipe.delete(valid_key)
            await pipe.set(revoked_key, 1)
            await pipe.expire(revoked_key, int(settings.REFRESH_TOKEN_EXPIRE_MINUTES * 60))
        # Clear the index set
        await pipe.delete(index_key)
        await pipe.execute()
