from __future__ import annotations
"""
LLM 工厂：统一构造 OpenAI/Azure 的客户端与 LangChain Chat 模型。

功能：
- build_chat_llm: 返回 ChatOpenAI/AzureChatOpenAI 以及上下文信息（provider_label、model_name）
- build_raw_client: 返回 OpenAI/AzureOpenAI 官方 SDK 客户端

策略：
- provider 归一化与自动识别（当 base_url/azure_endpoint 指向 Azure 风格时）
- 优先从凭证库（按 user_id+provider）读取，若未提供 user_id 或凭证缺失，则回退使用 cfg.client 中的值
- 统一处理 Azure endpoint 裁剪（去除 /openai/... 后缀）与部署名（azure_deployment）
"""

from typing import Any, Optional, Tuple
from pydantic import BaseModel

from langchain_openai import ChatOpenAI, AzureChatOpenAI
from openai import OpenAI, AzureOpenAI

from app.services.model_service import model_service
from app.schemas.model import InvokeConfig, OpenAIClient


class LLMContext(BaseModel):
    provider_label: Optional[str] = None
    model_name: Optional[str] = None
    # 对 Azure 来说表示部署名；对 OpenAI 表示模型名
    effective_model: Optional[str] = None


def _normalize_provider(provider: Optional[str]) -> Optional[str]:
    if not provider:
        return None
    p = provider.lower()
    if p in ("azure", "azure-openai", "azure_openai"):
        return "azure"
    if p in ("openai", "oai", "openai-compatible"):
        return "openai"
    return provider


def _auto_detect_provider_from_client(cfg: Optional[InvokeConfig], default: str = "openai") -> str:
    """当 provider 未显式给出时，根据 cfg.client 的端点自动识别 Azure。"""
    base_url_candidate = None
    azure_endpoint_candidate = None
    try:
        if cfg and getattr(cfg, "client", None):
            base_url_candidate = cfg.client.base_url
            azure_endpoint_candidate = cfg.client.azure_endpoint
    except Exception:
        pass
    lowered_bu = (base_url_candidate or "").lower()
    lowered_ae = (azure_endpoint_candidate or "").lower()
    if (
        "cognitiveservices.azure.com" in lowered_bu
        or "/openai/deployments/" in lowered_bu
        or "cognitiveservices.azure.com" in lowered_ae
    ):
        return "azure"
    return default


async def build_chat_llm(
    *,
    user_id: Optional[str],
    cfg: InvokeConfig | dict | None,
    provider: Optional[str] = None,
) -> Tuple[ChatOpenAI | AzureChatOpenAI, LLMContext]:
    """
    构造 LangChain Chat 模型（OpenAI/Azure）。

    参数：
    - user_id: 可选。若提供则优先从凭证库读取；否则仅使用 cfg.client 中的配置
    - cfg: 调用配置（或 dict，会自动转型）
    - provider: 可选。若未提供则基于 cfg 自动识别（默认 openai）
    返回： (llm, ctx)
    """
    # 归一化配置
    cfg = model_service.coerce_invoke_config(cfg)
    model_name = (getattr(cfg, "name", None) or "gpt-4o") if cfg else "gpt-4o"

    # provider 判定
    prov = _normalize_provider(provider)
    if not prov:
        prov = _auto_detect_provider_from_client(cfg, default="openai")
    p_lower = prov.lower()

    # 统一上下文标签
    ctx = LLMContext(
        provider_label=(
            "AzureOpenAI" if p_lower == "azure" else (
                "OpenAI" if p_lower == "openai" else prov
            )
        ),
        model_name=model_name,
    )

    # 采样参数
    temperature: float = 0.7
    max_completion_tokens: Optional[int] = None
    try:
        if cfg and getattr(cfg, "parameters", None) and cfg.parameters.temperature is not None:
            temperature = float(cfg.parameters.temperature)
        if cfg and getattr(cfg, "parameters", None) and cfg.parameters.max_completion_tokens is not None:
            max_completion_tokens = int(cfg.parameters.max_completion_tokens)
    except Exception:
        pass

    # 组装凭证与客户端参数（优先凭证库，回退 cfg.client）
    creds: dict[str, Any] = {}
    if user_id:
        try:
            creds = await model_service.get_provider_credentials(user_id=user_id, provider=prov, reveal_secret=True)
        except Exception:
            creds = {}
    client: OpenAIClient | None = getattr(cfg, "client", None) if cfg else None

    api_key = creds.get("api_key") or (client.api_key if client else None)
    base_url = creds.get("base_url") or (client.base_url if client else None)
    organization = creds.get("organization") or (client.organization if client else None)
    azure_endpoint = creds.get("azure_endpoint") or (client.azure_endpoint if client else None)
    api_version = creds.get("api_version") or (client.api_version if client else None)
    deployment_name = creds.get("azure_deployment") or model_name

    # 归一化 Azure endpoint（裁剪 /openai/... 后缀）
    if p_lower == "azure":
        if azure_endpoint:
            azure_endpoint = model_service.derive_azure_endpoint(azure_endpoint)
        elif base_url:  # 允许 base_url 传 Azure 全路径
            azure_endpoint = model_service.derive_azure_endpoint(base_url)

    # 构造 LLM
    if p_lower == "azure":
        if not api_key or not azure_endpoint or not api_version:
            raise ValueError("Missing Azure credentials (api_key/endpoint/api_version)")
        llm = AzureChatOpenAI(
            api_key=api_key,
            azure_endpoint=azure_endpoint,
            api_version=api_version,
            azure_deployment=deployment_name,
            max_completion_tokens=max_completion_tokens,
        )
        ctx.effective_model = deployment_name
        return llm, ctx

    elif p_lower == "openai":
        if not api_key:
            raise ValueError("Missing provider API key")
        llm = ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url=base_url,
            organization=organization,
            temperature=temperature,
            max_completion_tokens=max_completion_tokens,
        )
        ctx.effective_model = model_name
        return llm, ctx

    else:
        raise ValueError(f"Unsupported provider: {prov}")


async def build_raw_client(
    *,
    user_id: Optional[str],
    cfg: InvokeConfig | dict | None,
    provider: Optional[str] = None,
) -> Tuple[OpenAI | AzureOpenAI, LLMContext]:
    """
    构造官方 SDK 客户端（OpenAI/AzureOpenAI）。
    用于不依赖 LangChain 的直接 API 调用场景（如简单标题生成）。
    """
    cfg = model_service.coerce_invoke_config(cfg)
    model_name = (getattr(cfg, "name", None) or "gpt-4o") if cfg else "gpt-4o"

    prov = _normalize_provider(provider)
    if not prov:
        prov = _auto_detect_provider_from_client(cfg, default="openai")
    p_lower = prov.lower()

    ctx = LLMContext(
        provider_label=(
            "AzureOpenAI" if p_lower == "azure" else (
                "OpenAI" if p_lower == "openai" else prov
            )
        ),
        model_name=model_name,
    )

    creds: dict[str, Any] = {}
    if user_id:
        try:
            creds = await model_service.get_provider_credentials(user_id=user_id, provider=prov, reveal_secret=True)
        except Exception:
            creds = {}
    client: OpenAIClient | None = getattr(cfg, "client", None) if cfg else None

    api_key = creds.get("api_key") or (client.api_key if client else None)
    base_url = creds.get("base_url") or (client.base_url if client else None)
    organization = creds.get("organization") or (client.organization if client else None)
    azure_endpoint = creds.get("azure_endpoint") or (client.azure_endpoint if client else None)
    api_version = creds.get("api_version") or (client.api_version if client else None)
    deployment_name = creds.get("azure_deployment") or model_name

    if p_lower == "azure":
        if azure_endpoint:
            azure_endpoint = model_service.derive_azure_endpoint(azure_endpoint)
        elif base_url:
            azure_endpoint = model_service.derive_azure_endpoint(base_url)
        if not api_key or not azure_endpoint or not api_version:
            raise ValueError("Missing Azure credentials (api_key/endpoint/api_version)")
        client_sdk = AzureOpenAI(azure_endpoint=azure_endpoint, api_key=api_key, api_version=api_version)
        ctx.effective_model = deployment_name
        # 注：调用时请使用 deployment_name 作为 model
        return client_sdk, ctx
    elif p_lower == "openai":
        if not api_key:
            raise ValueError("Missing provider API key")
        client_sdk = OpenAI(api_key=api_key, base_url=base_url, organization=organization)
        ctx.effective_model = model_name
        return client_sdk, ctx
    else:
        raise ValueError(f"Unsupported provider: {prov}")
