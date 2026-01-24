from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.tool import ToolType, Tool, ToolTypeEnum
from app.crud.base_crud import CRUDBase
from app.schemas.tool import ToolCreate, ToolUpdate
from app.crud.mixins import CRUDUserFilterMixin
from typing import List, Callable

class CRUDTool(CRUDBase[Tool, ToolCreate, ToolUpdate], CRUDUserFilterMixin):
    """🤖 智能体 CRUD（基于通用 CRUDBase）"""

    def __init__(self):
        super().__init__(Tool)

    async def get_tool_type(self, db_session: AsyncSession):
        """
        获取全部工具类型（MCP / API / 工具）
        """
        result = await db_session.execute(select(ToolType))
        return result.scalars().all()

    async def upsert_scanned_tools(self, scanned: list[dict], db_session: AsyncSession) -> list[Tool]:
        """根据扫描结果将工具注册到数据库（按 module+function 唯一）。
        - 若存在则更新 name/description/type/enabled
        - 若不存在则创建（user_id=None，type=TOOL，enabled=True）
        返回变更后的 Tool 列表
        """
        updated: list[Tool] = []
        for item in scanned:
            name = item.get("name")
            module = item.get("module")
            function = item.get("function")
            description = item.get("description")
            if not module or not function:
                # 缺少来源信息，跳过写库，仅用于观测
                continue
            # 查找已存在记录
            res = await db_session.execute(
                select(Tool).where(
                    (Tool.module == module) & (Tool.function == function) & (Tool.user_id == None)
                )
            )
            obj = res.scalar_one_or_none()
            if obj:
                # 更新基础元信息
                obj.name = name or obj.name
                obj.description = description or obj.description
                obj.type = obj.type or ToolTypeEnum.TOOL
                obj.enabled = True
                db_session.add(obj)
                await db_session.commit()
                await db_session.refresh(obj)
                updated.append(obj)
            else:
                # 创建新记录
                new_obj = Tool(
                    user_id=None,
                    name=name or f"{module}.{function}",
                    description=description,
                    type=ToolTypeEnum.TOOL,
                    scene=None,
                    module=module,
                    function=function,
                    enabled=True,
                    invoke_config=None,
                )
                db_session.add(new_obj)
                await db_session.commit()
                await db_session.refresh(new_obj)
                updated.append(new_obj)
        return updated

# ✅ 实例化单例
crud_tool = CRUDTool()
