import logging
import asyncio
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tool.tool_loader import ToolLoader
from app.crud.tool_crud import crud_tool
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


async def sync_scanned_tools(db_session: AsyncSession) -> List:
    """
    将当前扫描到的工具（ToolLoader.get_scanned_tools_for_registry）同步注册到数据库。
    - 根据 module+function 唯一键进行 upsert
    - 返回变更后的 Tool 列表
    """
    scanned = ToolLoader.get_scanned_tools_for_registry()
    updated = await crud_tool.upsert_scanned_tools(scanned=scanned, db_session=db_session)
    return updated


def sync_scanned_tools_threadsafe() -> None:
    """
    在线程/同步环境中触发一次自动注册：
    - 启动一个新的事件循环
    - 创建 AsyncSession 并执行同步逻辑
    供 ToolWatcher 在文件变更重扫后调用。
    """
    async def _run():
        async with SessionLocal() as session:
            try:
                updated = await sync_scanned_tools(db_session=session)
                logger.info("🗃️ 自动注册完成，变更 %d 条工具", len(updated))
            except Exception as e:
                logger.exception("❌ 自动注册失败: %s", e)

    try:
        asyncio.run(_run())
    except Exception as e:
        logger.exception("❌ 启动事件循环失败: %s", e)
