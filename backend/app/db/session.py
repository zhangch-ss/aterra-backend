# https://stackoverflow.com/questions/75252097/fastapi-testing-runtimeerror-task-attached-to-a-different-loop/75444607#75444607
from sqlalchemy.orm import sessionmaker
from app.core.config import ModeEnum, settings
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.pool import NullPool, AsyncAdaptedQueuePool

# Use pool sizing derived from settings to avoid duplication.
# settings provides DB_POOL_SIZE, WEB_CONCURRENCY and POOL_SIZE.

common_engine_kwargs = {
    "echo": False,
}

# Main application engine
engine_pool_kwargs = {}
if settings.MODE != ModeEnum.testing and isinstance(getattr(settings, "POOL_SIZE", None), int):
    # Only set pool_size when a concrete int is provided
    engine_pool_kwargs["pool_size"] = int(settings.POOL_SIZE)  # type: ignore[arg-type]

engine = create_async_engine(
    str(settings.ASYNC_DATABASE_URI),
    poolclass=(NullPool if settings.MODE == ModeEnum.testing else AsyncAdaptedQueuePool),
    # Apply unified pool sizing from settings when using a QueuePool variant
    **engine_pool_kwargs,
    **common_engine_kwargs,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Removed legacy Celery-specific engine and session factory (unused)
