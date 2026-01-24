from typing import Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

# ======== OpenAI-compatible invoke parameters ========
class InvokeParameters(BaseModel):
    temperature: float | None = Field(default=0.7, ge=0.0, le=2.0)
    # Canonical field; accept legacy 'max_tokens' on input via model_validate override
    max_completion_tokens: int | None = Field(default=2048, ge=1)
    top_p: float | None = Field(default=1.0, ge=0.0, le=1.0)
    frequency_penalty: float | None = Field(default=0.0, ge=-2.0, le=2.0)
    presence_penalty: float | None = Field(default=0.0, ge=-2.0, le=2.0)
    timeout: int | None = Field(default=None, description="request timeout seconds")
    model_config = ConfigDict(populate_by_name=True)

    @classmethod
    def model_validate(cls, obj, *, strict=None, from_attributes=None, context=None):
        # Normalize legacy input key 'max_tokens' -> canonical 'max_completion_tokens'
        if isinstance(obj, dict) and "max_tokens" in obj and "max_completion_tokens" not in obj:
            try:
                obj = {**obj, "max_completion_tokens": obj.get("max_tokens")}
            except Exception:
                pass
        return super().model_validate(obj, strict=strict, from_attributes=from_attributes, context=context)


class OpenAIClient(BaseModel):
    # Generic/OpenAI
    base_url: str | None = None
    api_key: str | None = None
    organization: str | None = None
    # Azure OpenAI
    azure_endpoint: str | None = None
    api_version: str | None = None
    # Extra
    headers: dict[str, str] | None = None


class InvokeConfig(BaseModel):
    """Model invocation configuration supporting OpenAI-compatible format."""
    name: str = Field(description="Provider model id or deployment name")
    description: str | None = None
    parameters: InvokeParameters | None = None
    client: OpenAIClient | None = None
    meta: dict[str, Any] | None = None

    @classmethod
    def model_validate(cls, obj, *, strict=None, from_attributes=None, context=None):
        # Normalize legacy 'parameters.max_tokens' to 'parameters.max_completion_tokens'
        if isinstance(obj, dict):
            params = obj.get("parameters")
            if isinstance(params, dict) and "max_tokens" in params and "max_completion_tokens" not in params:
                try:
                    obj = {**obj, "parameters": {**params, "max_completion_tokens": params.get("max_tokens")}}
                except Exception:
                    pass
        return super().model_validate(obj, strict=strict, from_attributes=from_attributes, context=context)


# ======== Base structures (Card for nested usage) ========
class ModelBase(BaseModel):
    """Model card used for nested outputs; supports both 'description' and 'desc'."""
    id: str
    name: str
    description: str | None = None
    desc: str | None = None
    provider: str
    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def model_validate(cls, obj, *, strict=None, from_attributes=None, context=None):
        # ensure desc mirrors description when building from ORM attributes
        instance = super().model_validate(obj, strict=strict, from_attributes=from_attributes, context=context)
        if instance.desc is None and instance.description is not None:
            instance.desc = instance.description
        return instance


# ======== Create (input without id) ========
class ModelCreateInput(BaseModel):
    name: str
    description: str | None = Field(default=None, alias="desc")
    provider: str
    invoke_config: InvokeConfig | None = None
    model_config = ConfigDict(populate_by_name=True)


# ======== Update ========
class ModelUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    provider: str | None = None
    invoke_config: InvokeConfig | None = None


# ======== Read/Out ========
class ModelRead(ModelBase):
    created_at: datetime
    updated_at: datetime
    invoke_config: InvokeConfig | None = None
    model_config = ConfigDict(from_attributes=True)
