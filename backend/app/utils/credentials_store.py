from typing import Optional, Any
from redis.asyncio import Redis  # 兼容旧签名，实际不使用 Redis

from app.core.config import settings
from app.db.session import SessionLocal
from app.crud.provider_credentials_crud import crud_provider_credentials


# Redis key templates（兼容保留，不再使用）
CRED_HASH_KEY = "user:{user_id}:provider:{provider}:cred"


def get_redis_client() -> Redis:
    """兼容旧接口的工厂函数。
    说明：凭据已改为直接存数据库，Redis 客户端不再使用，仅保留以避免上层改动。
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
    """将 Provider 凭据直接以明文存入 PostgreSQL。
    注意：为简化使用，已移除加密/解密流程，api_key 直接存放在 provider_credentials.api_key_enc 字段中。
    如需后续迁移为新的列名，可再添加 Alembic 迁移。
    """
    values: dict[str, Any] = {}
    if api_key is not None:
        # 直接明文存储（复用现有列名，避免立刻做迁移）
        values["api_key_enc"] = api_key
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
    """从 PostgreSQL 获取 Provider 凭据（明文存储）。
    - 默认不返回 api_key，仅返回 has_api_key 标志
    - 当 reveal_secret=True 时，直接返回明文 api_key
    - 兼容旧数据：如果库里存的是历史加密值，会尝试解密，成功后自动写回明文
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
            api_key_value = rec.api_key_enc
            # 尝试兼容旧的加密密文（Fernet）。若能解密，则返回解密后的明文并写回数据库以去除加密。
            try:
                # 延迟导入，避免硬性依赖
                from app.utils.crypto import decrypt_text  # type: ignore
                decrypted = None
                try:
                    # 一些 Fernet 密文以 'gAAAA' 开头，但不强依赖前缀判断，直接尝试解密
                    decrypted = decrypt_text(api_key_value)
                except Exception:
                    decrypted = None
                if decrypted:
                    api_key_value = decrypted
                    # 将明文回写，彻底移除加密依赖
                    await crud_provider_credentials.upsert(
                        db_session=session,
                        user_id=user_id,
                        provider=provider,
                        values={"api_key_enc": decrypted},
                    )
                # else: 解密失败，视为已是明文
            except Exception:
                # crypto 不可用或其他异常，直接按明文返回
                pass
            result["api_key"] = api_key_value
    else:
        result["has_api_key"] = False

    return result  # type: ignore[return-value]


async def delete_provider_credentials(redis: Redis, user_id: str, provider: str) -> None:
    """删除指定用户在指定 Provider 下的凭据记录。"""
    async with SessionLocal() as session:
        await crud_provider_credentials.delete_by_user_provider(
            db_session=session,
            user_id=user_id,
            provider=provider,
        )
