from typing import Optional
from sqlmodel import Field, SQLModel
from sqlalchemy import UniqueConstraint
from app.models.base import BaseTable


class ProviderCredentials(BaseTable, table=True):
    """用户-Provider 级别的模型调用凭据（落库持久化，敏感字段加密存储）"""
    __tablename__ = "provider_credentials"
    user_id: str = Field(foreign_key="user.id", index=True, description="所属用户 ID")
    provider: str = Field(max_length=50, index=True, description="模型提供方，如 'openai' / 'azure' 等")

    # 加密后的密钥
    api_key_enc: Optional[str] = Field(default=None, description="加密存储的 API Key")

    # 其余非敏感配置
    base_url: Optional[str] = Field(default=None, description="可选：OpenAI 兼容 Base URL")
    organization: Optional[str] = Field(default=None, description="可选：OpenAI 组织 ID")
    azure_endpoint: Optional[str] = Field(default=None, description="可选：Azure OpenAI 端点")
    api_version: Optional[str] = Field(default=None, description="可选：Azure/OpenAI API 版本")
    azure_deployment: Optional[str] = Field(default=None, description="可选：Azure 部署名称（embeddings 需要）")

    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_provider_credentials_user_provider"),
    )
