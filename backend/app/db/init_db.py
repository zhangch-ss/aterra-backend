from sqlmodel.ext.asyncio.session import AsyncSession
from app.db.seeds.seed_tool_types import seed_tool_types


async def init_db(db_session: AsyncSession) -> None:
    """Initialize database with required minimal seeds.

    Currently seeds ToolType entries (MCP, API, 工具). This function is idempotent
    and avoids any references to non-existent schemas or CRUD modules.
    """
    await seed_tool_types(db_session)
