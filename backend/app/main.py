from fastapi import (
    FastAPI,
)
from fastapi_async_sqlalchemy import SQLAlchemyMiddleware
from sqlalchemy.pool import NullPool, AsyncAdaptedQueuePool
from starlette.middleware.cors import CORSMiddleware

from app.api.v1.api import api_router as api_router_v1
from app.core.config import ModeEnum, settings
from app.utils.fastapi_globals import GlobalsMiddleware
from app.core.tool.tool_watcher import start_tool_watcher, stop_tool_watcher
from contextlib import asynccontextmanager
from app.db.session import SessionLocal
from app.db.seeds.seed_tool_types import seed_tool_types
from fastapi_pagination import add_pagination
from app.core.tool.tool_loader import ToolLoader
from app.core.tool.tool_registry import sync_scanned_tools
from fastapi.responses import JSONResponse
from app.utils.logger import setup_logger


# Basic health/ready endpoints
def _ok(payload: dict[str, str] | None = None) -> JSONResponse:
    data = {"status": "ok"}
    if payload:
        data.update(payload)
    return JSONResponse(status_code=200, content=data)


logger = setup_logger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ✅ 启动前逻辑
    # Seed default ToolType rows (idempotent)
    try:
        async with SessionLocal() as session:
            await seed_tool_types(session)
            logger.info("✅ Seeded default ToolType rows (MCP, API, 工具)")
            # 🧩 可选：启动前扫描一次工具并自动注册到数据库（按配置开关）
            if getattr(settings, "TOOL_AUTO_SCAN_ON_START", False):
                try:
                    ToolLoader.clear_cache()
                    ToolLoader._scan_all_tools()
                    updated = await sync_scanned_tools(session)
                    logger.info(f"🗃️ 已自动注册扫描到的工具：{len(updated)} 条")
                except Exception as se:
                    logger.warning(f"⚠️ 启动前自动注册失败: {se}")
            else:
                logger.info("ℹ️ 跳过启动期自动扫描/注册（TOOL_AUTO_SCAN_ON_START=False）")
    except Exception as e:
        logger.warning(f"⚠️ ToolType seeding skipped: {e}")

    if getattr(settings, "TOOL_WATCHER_ENABLE", False):
        start_tool_watcher()
        logger.info("🚀 FastAPI 启动完成，已开启工具目录监控。")
    else:
        logger.info("🚀 FastAPI 启动完成（未启用工具目录监控）。")

    yield  # 👈 此处挂起应用运行

    # ✅ 关闭后逻辑
    logger.info("🛑 FastAPI 即将关闭，停止工具监控。")
    try:
        if getattr(settings, "TOOL_WATCHER_ENABLE", False):
            stop_tool_watcher()
    except Exception as e:
        logger.warning(f"⚠️ 停止工具监控异常: {e}")


# Core Application Instance
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.API_VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)


app.add_middleware(
    SQLAlchemyMiddleware,
    db_url=str(settings.ASYNC_DATABASE_URI),
    engine_args={
        "echo": False,
        "poolclass": NullPool
        if settings.MODE == ModeEnum.testing
        else AsyncAdaptedQueuePool
        # "pool_pre_ping": True,
        # "pool_size": settings.POOL_SIZE,
        # "max_overflow": 64,
    },
)
# app.add_middleware(GlobalsMiddleware)  # Temporarily disabled to resolve request scope assertion

# Set all CORS origins enabled
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.get("/")
async def root():
    """
    An example "Hello world" FastAPI route.
    """
    # if oso.is_allowed(user, "read", message):
    return {"message": "Hello World"}


@app.get("/healthz", include_in_schema=False)
async def healthz():
    return _ok({"version": settings.API_VERSION})


@app.get("/readyz", include_in_schema=False)
async def readyz():
    # 若需要，可在此增加对数据库/缓存/对象存储等的探测
    return _ok({"version": settings.API_VERSION})

# Add Routers
app.include_router(api_router_v1, prefix=settings.API_V1_STR)
add_pagination(app)
