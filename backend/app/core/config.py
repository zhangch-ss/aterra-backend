import os
from pathlib import Path
from pydantic_core.core_schema import FieldValidationInfo
from pydantic import PostgresDsn, EmailStr, AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Any
import secrets
from enum import Enum


class ModeEnum(str, Enum):
    development = "development"
    production = "production"
    testing = "testing"


class Settings(BaseSettings):
    MODE: ModeEnum = ModeEnum.development
    API_VERSION: str = "v1"
    API_V1_STR: str = f"/api/{API_VERSION}"
    PROJECT_NAME: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8  # 1 hour
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 100  # 100 days
    DATABASE_USER: str
    DATABASE_PASSWORD: str
    DATABASE_HOST: str
    DATABASE_PORT: int
    DATABASE_NAME: str
    REDIS_HOST: str
    REDIS_PORT: str
    DB_POOL_SIZE: int = 83
    WEB_CONCURRENCY: int = 9
    # Derive POOL_SIZE from DB_POOL_SIZE and WEB_CONCURRENCY when not explicitly provided.
    # Using a validator below ensures env overrides are respected.
    POOL_SIZE: int | None = None
    ASYNC_DATABASE_URI: PostgresDsn | str = ""

    # Tool integration configuration
    TOOL_PACKAGES: list[str] | None = [
        "app.core.tool.tools"
    ]
    # 控制启动时是否自动扫描工具并同步写库（默认关闭，改为手动入库+按需加载）
    TOOL_AUTO_SCAN_ON_START: bool = False
    # 控制是否启用工具目录文件监控（默认关闭）
    TOOL_WATCHER_ENABLE: bool = False
    # Cross-platform work directory for agent backends
    WORK_DIR: str = str(Path(__file__).parent.parent.parent / "work")

    # Local auth bypass (for development convenience only)
    # When enabled in development mode, endpoints using get_current_user will bypass
    # token verification and use/auto-create a local debug user.
    AUTH_LOCAL_MODE: bool = False
    AUTH_LOCAL_USERNAME: str | None = "local"
    AUTH_LOCAL_EMAIL: str | None = "local@example.com"
    AUTH_LOCAL_IS_SUPERUSER: bool = True

    # Security hardening for provider credentials storage
    # When False (default), encryption failures will NOT fallback to plaintext storage.
    # Set to True only in controlled dev environments to allow legacy/plaintext migration.
    ALLOW_PLAINTEXT_SECRET_FALLBACK: bool = False

    @field_validator("ASYNC_DATABASE_URI", mode="after")
    def assemble_db_connection(cls, v: str | None, info: FieldValidationInfo) -> Any:
        if isinstance(v, str):
            if v == "":
                return PostgresDsn.build(
                    scheme="postgresql+asyncpg",
                    username=info.data["DATABASE_USER"],
                    password=info.data["DATABASE_PASSWORD"],
                    host=info.data["DATABASE_HOST"],
                    port=info.data["DATABASE_PORT"],
                    path=info.data["DATABASE_NAME"],
                )
        return v

    # Derive POOL_SIZE after settings are loaded if not provided explicitly
    @field_validator("POOL_SIZE", mode="after")
    def derive_pool_size(cls, v: int | None, info: FieldValidationInfo) -> int | None:
        if v is None:
            try:
                db_pool_size = int(info.data.get("DB_POOL_SIZE"))
                web_conc = int(info.data.get("WEB_CONCURRENCY")) or 1
                return max(db_pool_size // max(web_conc, 1), 5)
            except Exception:
                # If any issue, keep None so engine uses defaults
                return None
        return v

    FIRST_SUPERUSER_EMAIL: EmailStr
    FIRST_SUPERUSER_PASSWORD: str

    MINIO_ROOT_USER: str
    MINIO_ROOT_PASSWORD: str
    MINIO_URL: str
    MINIO_BUCKET: str
    MINIO_INTERNAL_URL: str | None = None

    # Milvus (Vector DB) settings
    MILVUS_HOST: str = "milvus"
    MILVUS_PORT: int = 19530
    MILVUS_USER: str | None = None
    MILVUS_PASSWORD: str | None = None
    MILVUS_DB: str | None = None
    MILVUS_TLS: bool = False

    SECRET_KEY: str = secrets.token_urlsafe(32)
    ENCRYPT_KEY: str = secrets.token_urlsafe(32)
    # 默认不放开 CORS，需在环境变量中显式配置（例如："http://localhost:3000,http://127.0.0.1:3000"）
    BACKEND_CORS_ORIGINS: list[str] | list[AnyHttpUrl] = []

    @field_validator("BACKEND_CORS_ORIGINS")
    def assemble_cors_origins(cls, v: str | list[str]) -> list[str] | str:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    model_config = SettingsConfigDict(
        case_sensitive=True,
        # 允许通过 ENV_FILE 指定 .env 路径；默认为项目根目录 .env
        env_file=os.getenv(
            "ENV_FILE",
            str(Path(__file__).resolve().parents[2] / ".env"),
        ),
        extra="ignore",
    )

    # Enforce SECRET_KEY must be explicitly provided in production
    @field_validator("SECRET_KEY", mode="after")
    def validate_secret_key(cls, v: str, info: FieldValidationInfo) -> str:
        try:
            mode = info.data.get("MODE")
        except Exception:
            mode = None
        if str(mode) == ModeEnum.production and not os.getenv("SECRET_KEY"):
            raise ValueError("SECRET_KEY must be provided via environment variable in production")
        return v


settings = Settings()  # type: ignore