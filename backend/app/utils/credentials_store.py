from typing import Optional, Any
from redis.asyncio import Redis  # 仅保留类型兼容，实际不再使用 Redis

from app.core.config import settings
from app.utils.crypto import encrypt_text, decrypt_text
from app.db.session import SessionLocal
from app.crud.provider_credentials_crud import crud_provider_credentials


# Redis key templates（兼容保留，不再使用）
CRED_HASH_KEY = "user:{user_id}:provider:{provider}:cred"


def get_redis_client() -> Redis:
    """兼容旧接口的工厂函数（调用方仍可获取 Redis 客户端）。
    实际存储已迁移到 PostgreSQL，此函数返回值不会被使用。
    """
    return Redis(host=settings.REDIS_HOST, port=int(settings.REDIS_PORT), decode_responses=True)


async def store_provider_credentials(
    redis: Redis,  # 兼容占位，实际不使用
    user_id: str,
    provider: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    organization: Optional[str] = None,
    azure_endpoint: Optional[str] = None,
    api_version: Optional[str] = None,
    azure_deployment: Optional[str] = None,
) -> None:
    """将 Provider 凭据落库到 PostgreSQL。
    - 敏感字段 api_key 使用 encrypt_text 加密后存储到 api_key_enc
    - 其余字段原样存储
    """
    values: dict[str, Any] = {}
    if api_key:
        values["api_key_enc"] = encrypt_text(api_key)
    if base_url is not None:
        values["base_url"] = base_url
    if organization is not None:
        values["organization"] = organization
    if azure_endpoint is not None:
        values["azure_endpoint"] = azure_endpoint
    if api_version is not None:
        values["api_version"] = api_version
    if azure_deployment is not None:
        values["azure_deployment"] = azure_deployment

    async with SessionLocal() as session:
        await crud_provider_credentials.upsert(
            db_session=session,
            user_id=user_id,
            provider=provider,
            values=values,
        )


async def get_provider_credentials(
    redis: Redis,  # 兼容占位，实际不使用
    user_id: str,
    provider: str,
    reveal_secret: bool = False,
) -> dict[str, Optional[str]]:
    """从 PostgreSQL 获取 Provider 凭据。
    - 默认不返回明文 api_key，仅返回 has_api_key 标志
    - 当 reveal_secret=True 时，解密 api_key_enc 返回明文 api_key
    """
    async with SessionLocal() as session:
        rec = await crud_provider_credentials.get_by_user_provider(
            db_session=session,
            user_id=user_id,
            provider=provider,
        )

    if not rec:
        return {}

    result: dict[str, Optional[str] | bool] = {
        "base_url": rec.base_url,
        "organization": rec.organization,
        "azure_endpoint": rec.azure_endpoint,
        "api_version": rec.api_version,
        "azure_deployment": rec.azure_deployment,
    }

    if rec.api_key_enc:
        result["has_api_key"] = True
        if reveal_secret:
            try:
                result["api_key"] = decrypt_text(rec.api_key_enc)
            except Exception:
                result["api_key"] = None
    else:
        result["has_api_key"] = False

    # 不打印敏感信息，避免日志泄露
    return result  # type: ignore[return-value]


async def delete_provider_credentials(redis: Redis, user_id: str, provider: str) -> None:
    """删除指定用户在指定 Provider 下的凭据记录。"""
    async with SessionLocal() as session:
        await crud_provider_credentials.delete_by_user_provider(
            db_session=session,
            user_id=user_id,
            provider=provider,
        )
