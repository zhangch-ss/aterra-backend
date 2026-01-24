#!/usr/bin/env python3
"""
工具入库脚本：扫描 BaseTool/StructuredTool 并写入数据库

用法示例：
    python -m scripts.tools_db_import --db-url "postgresql+asyncpg://postgres:zxc123456@database:5432/fastapi_db"

可选参数：
    --filter <str>         只导入名称包含该子串的工具（前缀/子串匹配）
    --enabled <bool>       写库时设置 enabled（默认 true）
    --packages <str,...>   逗号分隔的包列表，覆盖 settings.TOOL_PACKAGES（默认 app.core.tool.tools）
    --dry-run <bool>       仅打印将入库的条目，不写库（默认 false）

说明：
- 仅针对内置工具（user_id IS NULL）执行 upsert，唯一键为 (module,function)。
- 若需要按用户维度入库，可扩展 CRUDTool 方法后再增强脚本。
"""
import os
import sys
import asyncio
import logging
import argparse
from typing import List, Dict

# 允许直接在项目根目录执行
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 为避免 Settings 在构造 ASYNC_DATABASE_URI 时读取缺失的 DATABASE_* 环境变量，
# 预置占位的连接字符串以跳过拼装逻辑（dry-run 时不访问数据库）。
os.environ.setdefault("ASYNC_DATABASE_URI", "postgresql+asyncpg://user:pass@localhost:5432/placeholder_db")
os.environ.setdefault("SYNC_CELERY_DATABASE_URI", "postgresql+asyncpg://user:pass@localhost:5432/placeholder_db")
os.environ.setdefault("SYNC_CELERY_BEAT_DATABASE_URI", "postgresql+psycopg2://user:pass@localhost:5432/placeholder_db")
os.environ.setdefault("ASYNC_CELERY_BEAT_DATABASE_URI", "postgresql+asyncpg://user:pass@localhost:5432/placeholder_db")

from app.core.tool.tool_loader import ToolLoader
from typing import Optional
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlmodel import select
from app.models.tool import Tool, ToolTypeEnum
from app.core.tool.schema_extractor import (
    extract_tool_schema,
    extract_runtime_parameters,
    compute_schema_hash,
    now_ts,
)

logger = logging.getLogger("tools_db_import")
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


def parse_args():
    p = argparse.ArgumentParser(description="扫描工具并写入数据库（内置工具）")
    p.add_argument("--filter", type=str, default=None, help="只导入名称包含该子串的工具")
    p.add_argument("--enabled", type=str, default="true", help="导入后是否启用（true/false）")
    p.add_argument("--packages", type=str, default=None, help="逗号分隔包列表，覆盖 settings.TOOL_PACKAGES")
    p.add_argument("--dry-run", type=str, default="false", help="仅打印不写库（true/false）")
    p.add_argument("--with-schema", type=str, default="true", help="是否提取并入库 llm/runtime schema（true/false）")
    p.add_argument("--reset-params", type=str, default="false", help="是否重置 invoke_config.parameters（true/false）")
    p.add_argument("--db-url", type=str, default=None, help="数据库连接串（postgresql+asyncpg://...）。不提供则仅支持 --dry-run 模式")
    return p.parse_args()


def coerce_bool(s: str, default: bool) -> bool:
    try:
        val = s.strip().lower()
        if val in ("1", "true", "t", "yes", "y"): return True
        if val in ("0", "false", "f", "no", "n"): return False
        return default
    except Exception:
        return default


async def run():
    args = parse_args()

    # 覆盖扫描包（可选）
    if args.packages:
        pkgs = [x.strip() for x in args.packages.split(",") if x.strip()]
        ToolLoader.set_packages(pkgs)
        logger.info(f"📦 覆盖扫描包: {pkgs}")

    # 重新清空缓存，确保扫描最新内容
    try:
        ToolLoader.clear_cache()
    except Exception:
        pass

    scanned: List[Dict] = ToolLoader.get_scanned_tools_for_registry()

    # 过滤（按名称包含）
    if args.filter:
        scanned = [x for x in scanned if args.filter in (x.get("name") or "")]
        logger.info(f"🔎 按过滤 '{args.filter}' 后剩余 {len(scanned)} 项")

    # dry-run 仅打印
    dry_run = coerce_bool(args.dry_run, False)
    enabled = coerce_bool(args.enabled, True)
    with_schema = coerce_bool(args.with_schema, True)
    reset_params = coerce_bool(args.reset_params, False)

    if dry_run:
        logger.info("📝 Dry-run 模式，以下工具将被导入（未执行写库）：")
        for i, x in enumerate(scanned, 1):
            logger.info(f"  {i:02d}. {x.get('name')}  @ {x.get('module')}.{x.get('function')}  - {x.get('description')}")
        return

    # 执行写库（幂等）
    if not args.db_url:
        logger.error("需要提供 --db-url 以执行写库。示例：--db-url postgresql+asyncpg://user:pass@host:5432/dbname")
        return

    engine = create_async_engine(args.db_url, echo=False)
    AsyncSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as session:
        updated: List[Tool] = []
        for item in scanned:
            name = item.get("name")
            module = item.get("module")
            function = item.get("function")
            description = item.get("description")
            if not module or not function:
                continue

            # 可选：加载工具对象并提取 schema
            tool_schema = None
            runtime_parameters = None
            if with_schema:
                tool_obj = ToolLoader._load_tool_by_module_func(module, function)
                if tool_obj:
                    tool_schema = extract_tool_schema(tool_obj)
                    rp_schema = extract_runtime_parameters(tool_obj) or {}
                    runtime_parameters = {"schema": rp_schema, "values": {}}
                    schema_hash = compute_schema_hash(tool_schema, runtime_parameters)
                else:
                    logger.warning(f"无法加载工具对象以提取 schema: {module}.{function}")

            res = await session.execute(select(Tool).where((Tool.module == module) & (Tool.function == function) & (Tool.user_id == None)))
            obj = res.scalar_one_or_none()
            if obj:
                obj.name = name or obj.name
                obj.description = description or obj.description
                obj.type = obj.type or ToolTypeEnum.TOOL
                obj.enabled = enabled
                if with_schema:
                    obj.tool_schema = tool_schema
                    obj.runtime_parameters = runtime_parameters
                if reset_params:
                    # 重置运行时默认值容器
                    inv = getattr(obj, "invoke_config", None) or {}
                    if not isinstance(inv, dict):
                        inv = getattr(obj, "model_dump", lambda: {})()
                    inv["parameters"] = {}
                    obj.invoke_config = inv
                session.add(obj)
                await session.commit()
                await session.refresh(obj)
                updated.append(obj)
            else:
                new_obj = Tool(
                    user_id=None,
                    name=name or f"{module}.{function}",
                    description=description,
                    type=ToolTypeEnum.TOOL,
                    scene=None,
                    module=module,
                    function=function,
                    enabled=enabled,
                    invoke_config=None,
                    tool_schema=tool_schema,
                    runtime_parameters=runtime_parameters,
                )
                session.add(new_obj)
                await session.commit()
                await session.refresh(new_obj)
                updated.append(new_obj)
        logger.info(f"✅ 写库完成：共变更 {len(updated)} 条（enabled={enabled}）")


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("Interrupted")
