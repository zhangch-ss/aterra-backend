from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.tool import Tool

# 通用占位与安全键提示
MASK_SENTINEL = "***masked***"
SECURE_KEY_HINTS = {
    "api_key",
    "apikey",
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "client_secret",
    "password",
    "pwd",
    "access_key",
}


@dataclass
class RuntimeContext:
    """为工具注入的运行时上下文。
    - user_id: 当前用户
    - db: 异步数据库会话
    """
    user_id: str
    db: AsyncSession


async def find_tool_record(
    db: AsyncSession,
    user_id: str,
    *,
    tool_name: Optional[str] = None,
) -> Optional[Tool]:
    """按优先级仅用 (user_id, name) 查找 Tool 记录：
    1) 用户私有：user_id 精确 + name
    2) 内置默认：user_id IS NULL + name

    说明：为简化定位逻辑，移除了按 module/function 的匹配。
    若存在同名多条记录，本函数将返回查询到的第一条（按数据库默认顺序）。
    """

    if not tool_name:
        return None

    async def _query_by_name(cond_user: bool) -> Optional[Tool]:
        try:
            q = select(Tool).where(
                (Tool.user_id == (user_id if cond_user else None))
                & (Tool.name == tool_name)
            )
            res = await db.execute(q)
            # 使用 first() 避免多行导致的异常
            return res.scalars().first()
        except Exception:
            return None

    rec = await _query_by_name(cond_user=True)
    if rec:
        return rec
    rec = await _query_by_name(cond_user=False)
    if rec:
        return rec
    return None


async def get_tool_runtime_bundle(
    db: AsyncSession, user_id: str, *, tool_name: Optional[str]
) -> dict:
    """根据 (user_id, tool_name) 返回工具运行期配置包。

    返回结构：
    {"schema": dict|None, "values": dict, "secrets": dict, "record": Tool|None}
    """
    rec = await find_tool_record(db, user_id, tool_name=tool_name)
    rp = getattr(rec, "runtime_parameters", None) if rec else None
    if not isinstance(rp, dict):
        return {"schema": None, "values": {}, "secrets": {}, "record": rec}
    schema = rp.get("schema") if isinstance(rp, dict) else None
    values = rp.get("values", {}) if isinstance(rp, dict) else {}
    secrets = rp.get("secrets", {}) if isinstance(rp, dict) else {}
    return {"schema": schema, "values": values or {}, "secrets": secrets or {}, "record": rec}
