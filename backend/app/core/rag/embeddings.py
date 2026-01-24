from __future__ import annotations
from typing import Optional
from langchain_openai import OpenAIEmbeddings, AzureOpenAIEmbeddings
from app.core.config import settings
from app.utils.credentials_store import (
    get_redis_client,
    get_provider_credentials as _get_provider_credentials,
)


def _normalize_provider(provider: Optional[str]) -> str:
    if not provider:
        return "openai"
    p = provider.lower()
    if p in ("azure", "azure-openai", "azure_openai"):
        return "azure"
    if p in ("openai", "oai", "openai-compatible"):
        return "openai"
    return p


async def get_embeddings(
    user_id: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
):
    """Factory to create LangChain Embeddings for OpenAI or Azure OpenAI.
    - Reads per-user provider credentials from Redis (credentials_store)
    - Falls back to global settings if user credentials missing
    """
    prov = _normalize_provider(provider)
    redis = get_redis_client()
    creds = await _get_provider_credentials(redis, user_id=user_id, provider=prov, reveal_secret=True)

    if prov == "openai":
        api_key = creds.get("api_key") or getattr(settings, "OPENAI_API_KEY", None)
        base_url = creds.get("base_url") or None
        organization = creds.get("organization") or None
        # default model
        emb_model = model or "text-embedding-3-large"
        return OpenAIEmbeddings(
            model=emb_model,
            api_key=api_key,
            base_url=base_url,
            organization=organization,
        )
    elif prov == "azure":
        api_key = creds.get("api_key") or getattr(settings, "OPENAI_API_KEY", None)
        azure_endpoint = creds.get("azure_endpoint") or getattr(settings, "AZURE_OPENAI_ENDPOINT", None)
        api_version = creds.get("api_version") or getattr(settings, "OPENAI_API_VERSION", None)
        if not azure_endpoint:
            # try derive from base_url
            bu = creds.get("base_url")
            if bu:
                lowered = bu.lower()
                idx = lowered.find("/openai")
                azure_endpoint = bu[:idx] if idx != -1 else bu
        # AzureOpenAIEmbeddings 的 model 参数应为“部署名称”，而非原始模型名
        dep_name = None
        if model:
            # 如果调用方传入了 embed_model，则视为 Azure 部署名称
            dep_name = model
        else:
            # 尝试从用户凭据中读取预置的部署名称
            dep_name = creds.get("azure_deployment")
        if not dep_name:
            # 明确提示：Azure 需要部署名称，不能使用 OpenAI 原始模型名
            raise ValueError("Azure embeddings 需要传入 embed_model=部署名称或在凭据中配置 azure_deployment")
        return AzureOpenAIEmbeddings(
            model=dep_name,
            api_key=api_key,
            azure_endpoint=azure_endpoint,
            api_version=api_version,
        )
    else:
        raise ValueError(f"Unsupported provider for embeddings: {provider}")
