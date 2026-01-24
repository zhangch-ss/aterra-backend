from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy import text
from app.models.tool import ToolTypeEnum

async def seed_tool_types(db_session: AsyncSession) -> None:
    """Ensure default ToolType rows exist and are set on redeploy.

    Uses raw SQL with enum casting to avoid Python Enum name/value binding issues.
    """
    defaults = [
        (ToolTypeEnum.MCP.value, "Model Context Protocol tools"),
        (ToolTypeEnum.API.value, "HTTP API tools"),
        (ToolTypeEnum.TOOL.value, "内置/本地工具"),
    ]
    for label, desc in defaults:
        # Inline enum label (safe: constrained to known values) to avoid driver param/cast quirks
        exists_sql = text(f"SELECT id FROM tooltype WHERE name::text = '{label}'")
        exists_result = await db_session.execute(exists_sql)
        exists = exists_result.first()
        if not exists:
            insert_sql = text(f"INSERT INTO tooltype (name, description) VALUES ('{label}'::tooltypeenum, :desc)")
            await db_session.execute(insert_sql, {"desc": desc})
    await db_session.commit()
