from typing import Optional, Any

from app.db.session import SessionLocal
from app.core.config import settings
from app.crud.provider_credentials_crud import crud_provider_credentials
from app.utils.crypto import encrypt_text, decrypt_text


async def store_provider_credentials(
    user_id: str,
    provider: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    organization: Optional[str] = None,
    azure_endpoint: Optional[str] = None,
    api_version: Optional[str] = None,
    azure_deployment: Optional[str] = None,
) -> None:
    """存储 Provider 凭据。api_key 采用应用层加密后再入库，其余为明文配置。
    兼容历史数据：仅在本函数写入时加密；读取时若解密失败则回退为原始值。
    """
    values: dict[str, Any] = {}
    if api_key is not None:
        # Encrypt api_key at rest
        try:
            values["api_key_enc"] = encrypt_text(api_key)
        except Exception as enc_err:
            # 生产默认禁止明文回退；如需迁移/调试，可在开发环境显式开启
            if getattr(settings, "ALLOW_PLAINTEXT_SECRET_FALLBACK", False):
                values["api_key_enc"] = api_key
            else:
                raise ValueError(
                    "Failed to encrypt provider api_key and plaintext fallback is disabled."
                ) from enc_err
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
    user_id: str,
    provider: str,
    reveal_secret: bool = False,
) -> dict[str, Optional[str]]:
    """从 PostgreSQL 获取 Provider 凭据。
    - 默认不返回 api_key，仅返回 has_api_key 标志；
    - 当 reveal_secret=True 时，尝试解密返回明文；若解密失败则回退原始值（兼容历史明文）。
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
            # Try decrypt; fallback to raw if it's legacy plaintext
            try:
                result["api_key"] = decrypt_text(rec.api_key_enc)
            except Exception:
                result["api_key"] = rec.api_key_enc
    else:
        result["has_api_key"] = False

    return result  # type: ignore[return-value]


async def delete_provider_credentials(user_id: str, provider: str) -> None:
    """删除指定用户在指定 Provider 下的凭据记录。"""
    async with SessionLocal() as session:
        await crud_provider_credentials.delete_by_user_provider(
            db_session=session,
            user_id=user_id,
            provider=provider,
        )
