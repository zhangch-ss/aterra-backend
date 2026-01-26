from __future__ import annotations
from typing import Any, Optional, List
import time

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel
from openai import OpenAI, AzureOpenAI
from app.core.config import settings
from app.utils.logger import setup_logger

from app.crud.model_crud import crud_model
from app.models.model import Model
from app.schemas.model import InvokeConfig, ModelCreateInput, ModelUpdate
from app.utils.credentials_store import (
    get_redis_client,
    store_provider_credentials as _store_provider_credentials,
    get_provider_credentials as _get_provider_credentials,
    delete_provider_credentials as _delete_provider_credentials,
)


class ProviderCredentialsInput(BaseModel):
    api_key: str | None = None
    base_url: str | None = None
    organization: str | None = None
    azure_endpoint: str | None = None
    api_version: str | None = None
    azure_deployment: str | None = None


class ModelVerifyInput(BaseModel):
    model_id: str | None = None
    invoke_config: InvokeConfig | None = None
    provider: str | None = None


class ModelService:
    def __init__(self) -> None:
        self.logger = setup_logger(self.__class__.__name__)
    """Service for managing model registry, configuration, credentials and verification.
    Centralizes logic under app.core.model.
    """

    @staticmethod
    def sanitize_invoke_config(cfg: InvokeConfig | None) -> InvokeConfig | None:
        """Sanitize invoke config before persistence: drop sensitive secrets.
        - remove client.api_key and Authorization-like headers
        """
        if not cfg:
            return None
        data = cfg.model_dump(exclude_none=True)
        client = data.get("client")
        if client:
            client.pop("api_key", None)
            headers = client.get("headers")
            if headers:
                client["headers"] = {k: v for k, v in headers.items() if k.lower() != "authorization"}
        return InvokeConfig.model_validate(data)

    @staticmethod
    def coerce_invoke_config(cfg: InvokeConfig | dict | None) -> InvokeConfig | None:
        """Coerce possible dict (from DB JSON or raw payload) into InvokeConfig model."""
        if cfg is None:
            return None
        if isinstance(cfg, InvokeConfig):
            return cfg
        try:
            return InvokeConfig.model_validate(cfg)
        except Exception:
            return None

    @staticmethod
    def derive_azure_endpoint(base_url: str | None) -> str | None:
        """Derive Azure endpoint from a full base_url that may include '/openai/deployments/...'."""
        if not base_url:
            return None
        lowered = base_url.lower()
        idx = lowered.find("/openai")
        return (base_url[:idx] if idx != -1 else base_url).rstrip("/")

    # CRUD operations
    async def list_models(
        self,
        user_id: str,
        db_session: AsyncSession,
        provider: Optional[str] = None,
        keyword: Optional[str] = None,
    ) -> List[Model]:
        return await crud_model.get_by_user_id(
            user_id=user_id,
            db_session=db_session,
            provider=provider,
            keyword=keyword,
        )

    async def get_owned_model(self, model_id: str, user_id: str, db_session: AsyncSession) -> Optional[Model]:
        m = await crud_model.get(id=model_id, db_session=db_session)
        if not m or m.user_id != user_id:
            return None
        return m

    async def create_model(self, payload: ModelCreateInput, user_id: str, db_session: AsyncSession) -> Model:
        # Build data dict from payload and inject ownership
        data = payload.model_dump(exclude_none=True)
        if payload.invoke_config:
            sanitized = self.sanitize_invoke_config(payload.invoke_config)
            # Persist as plain dict (JSON) after sanitization
            data["invoke_config"] = sanitized.model_dump(exclude_none=True)
        # Set owner from auth context
        data["user_id"] = user_id
        created = await crud_model.create(obj_in=data, created_by_id=user_id, db_session=db_session)
        return created

    async def update_model(self, model_id: str, payload: ModelUpdate, user_id: str, db_session: AsyncSession) -> Optional[Model]:
        current = await self.get_owned_model(model_id=model_id, user_id=user_id, db_session=db_session)
        if not current:
            return None
        if payload.invoke_config:
            payload.invoke_config = self.sanitize_invoke_config(payload.invoke_config)
        updated = await crud_model.update(obj_current=current, obj_new=payload, db_session=db_session)
        return updated

    async def delete_model(self, model_id: str, user_id: str, db_session: AsyncSession) -> bool:
        current = await self.get_owned_model(model_id=model_id, user_id=user_id, db_session=db_session)
        if not current:
            return False
        await crud_model.remove(id=model_id, db_session=db_session)
        return True

    # Credentials management (backed by Redis via utils.credentials_store)
    async def set_provider_credentials(self, user_id: str, provider: str, payload: ProviderCredentialsInput) -> None:
        redis = get_redis_client()
        await _store_provider_credentials(
            redis,
            user_id=user_id,
            provider=provider,
            api_key=payload.api_key,
            base_url=payload.base_url,
            organization=payload.organization,
            azure_endpoint=payload.azure_endpoint,
            api_version=payload.api_version,
            azure_deployment=payload.azure_deployment,
        )

    async def get_provider_credentials(self, user_id: str, provider: str, reveal_secret: bool = False) -> dict[str, Any]:
        redis = get_redis_client()
        return await _get_provider_credentials(redis, user_id=user_id, provider=provider, reveal_secret=reveal_secret)

    async def delete_provider_credentials(self, user_id: str, provider: str) -> None:
        redis = get_redis_client()
        await _delete_provider_credentials(redis, user_id=user_id, provider=provider)

    # Verification logic
    async def verify_model(
        self,
        user_id: str,
        db_session: AsyncSession,
        *,
        model_id: Optional[str] = None,
        provider: Optional[str] = None,
        invoke_config: Optional[InvokeConfig] = None,
    ) -> dict[str, Any]:
        """Verify if given model configuration and stored credentials are valid by performing
        a minimal completion call.
        Returns: { ok: bool, provider: str, model: str, latency_ms?: int, error?: str }
        """
        # Resolve cfg and provider
        cfg: Optional[InvokeConfig]
        prov: Optional[str]
        if model_id:
            current = await self.get_owned_model(model_id=model_id, user_id=user_id, db_session=db_session)
            if not current:
                return {"ok": False, "error": "Model not found or not owned"}
            cfg = current.invoke_config
            prov = current.provider
        else:
            cfg = invoke_config
            prov = provider

        # Coerce possible dicts into Pydantic model
        cfg = self.coerce_invoke_config(cfg)

        # Autodetect Azure-style base_url when provider is 'openai'
        if prov and prov.lower() in ("openai", "oai", "openai-compatible"):
            try:
                base_url_candidate = cfg.client.base_url if (cfg and getattr(cfg, "client", None)) else None
            except Exception:
                base_url_candidate = None
            if base_url_candidate:
                lowered_bu = base_url_candidate.lower()
                if "cognitiveservices.azure.com" in lowered_bu or "/openai/deployments/" in lowered_bu:
                    prov = "azure"

        if not prov:
            return {"ok": False, "error": "Missing provider"}
        if not cfg or not cfg.name:
            return {"ok": False, "provider": prov, "error": "Missing invoke_config.name"}

        # Read credentials (with clear api_key if reveal_secret=True)
        creds = await self.get_provider_credentials(user_id=user_id, provider=prov, reveal_secret=True)
        self.logger.debug("Verifying model. invoke_config=%s, provider=%s", cfg, prov)
        api_key = creds.get("api_key")
        base_url = creds.get("base_url") or (cfg.client.base_url if getattr(cfg, "client", None) else None)
        organization = creds.get("organization") or (cfg.client.organization if getattr(cfg, "client", None) else None)
        azure_endpoint = creds.get("azure_endpoint") or (cfg.client.azure_endpoint if getattr(cfg, "client", None) else None)
        temperature=1
        try:
            if cfg and getattr(cfg, "parameters", None) and cfg.parameters.temperature is not None:
                temperature = float(cfg.parameters.temperature)
            if cfg and getattr(cfg, "parameters", None) and cfg.parameters.max_completion_tokens is not None:
                max_completion_tokens = int(cfg.parameters.max_completion_tokens)
        except Exception:
            pass
        p_lower = prov.lower()
        # Normalize Azure endpoint regardless of source (creds or client), strip any '/openai...' suffix
        if p_lower in ("azure", "azure-openai"):
            if azure_endpoint:
                azure_endpoint = self.derive_azure_endpoint(azure_endpoint)
            else:
                azure_endpoint = self.derive_azure_endpoint(base_url)
        api_version = creds.get("api_version") or (cfg.client.api_version if getattr(cfg, "client", None) else None)

        start = time.time()
        p = prov.lower()
        if p in ("openai", "oai", "openai-compatible"):
            if not api_key:
                return {"ok": False, "provider": prov, "model": cfg.name, "error": "Missing provider API key"}
            client = OpenAI(api_key=api_key, base_url=base_url, organization=organization)
            def _call():
                return client.chat.completions.create(
                    model=cfg.name,
                    messages=[{"role": "user", "content": "ping"}],
                    temperature=temperature,
                    max_completion_tokens=max_completion_tokens,
                )
            await run_in_threadpool(_call)
        elif p in ("azure", "azure-openai"):
            if not api_key or not azure_endpoint or not api_version:
                return {
                    "ok": False,
                    "provider": prov,
                    "model": cfg.name,
                    "error": "Missing Azure credentials (api_key/endpoint/api_version)",
                }
            deployment_name = creds.get("azure_deployment") or cfg.name
            client = AzureOpenAI(azure_endpoint=azure_endpoint, api_key=api_key, api_version=api_version)
            def _call():
                return client.chat.completions.create(
                    model=deployment_name,
                    messages=[{"role": "user", "content": "ping"}],
                    max_completion_tokens=max_completion_tokens
                )
            await run_in_threadpool(_call)
        else:
            return {"ok": False, "error": f"Unsupported provider: {prov}"}

        elapsed = int((time.time() - start) * 1000)
        return {"ok": True, "provider": prov, "model": cfg.name, "latency_ms": elapsed}



# Singleton service
model_service = ModelService()
