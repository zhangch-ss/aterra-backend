from datetime import timedelta
from typing import Optional
from redis.asyncio import Redis

from app.core.config import settings


ACCESS_REVOKED_SET = "user:{user_id}:revoked"
REFRESH_VALID_SET = "user:{user_id}:refresh:valid"
REFRESH_REVOKED_SET = "user:{user_id}:refresh:revoked"
ACCESS_REFRESH_PAIR = "user:{user_id}:pair:{access_token}"


def get_redis_client() -> Redis:
    return Redis(host=settings.REDIS_HOST, port=int(settings.REDIS_PORT), decode_responses=True)


# Access token revocation (blacklist)
async def revoke_token(
    redis_client: Redis,
    user_id: str,
    token: str,
    expire_minutes: Optional[int] = None,
) -> None:
    key = ACCESS_REVOKED_SET.format(user_id=user_id)
    await redis_client.sadd(key, token)
    if expire_minutes:
        await redis_client.expire(key, timedelta(minutes=expire_minutes))


async def is_token_revoked(redis_client: Redis, user_id: str, token: str) -> bool:
    key = ACCESS_REVOKED_SET.format(user_id=user_id)
    return await redis_client.sismember(key, token)


# Refresh token allowlist and revocation
async def store_refresh_token(
    redis_client: Redis,
    user_id: str,
    refresh_token: str,
    expire_minutes: Optional[int] = None,
) -> None:
    key = REFRESH_VALID_SET.format(user_id=user_id)
    await redis_client.sadd(key, refresh_token)
    if expire_minutes:
        await redis_client.expire(key, timedelta(minutes=expire_minutes))


async def is_refresh_token_valid(redis_client: Redis, user_id: str, refresh_token: str) -> bool:
    key = REFRESH_VALID_SET.format(user_id=user_id)
    return await redis_client.sismember(key, refresh_token)


async def revoke_refresh_token(
    redis_client: Redis,
    user_id: str,
    refresh_token: str,
) -> None:
    # Move token from valid set to revoked set
    valid_key = REFRESH_VALID_SET.format(user_id=user_id)
    revoked_key = REFRESH_REVOKED_SET.format(user_id=user_id)
    async with redis_client.pipeline(transaction=True) as pipe:
        await pipe.srem(valid_key, refresh_token)
        await pipe.sadd(revoked_key, refresh_token)
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
    valid_key = REFRESH_VALID_SET.format(user_id=user_id)
    revoked_key = REFRESH_REVOKED_SET.format(user_id=user_id)
    # Move all valid refresh tokens to revoked set then delete valid set
    members = await redis_client.smembers(valid_key)
    if members:
        await redis_client.sadd(revoked_key, *members)
    await redis_client.delete(valid_key)
