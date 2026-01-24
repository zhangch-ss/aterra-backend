from typing import List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, distinct, or_, and_
from app.models.agent import Agent
from app.schemas.agent import AgentCreate, AgentUpdate
from app.crud.base_crud import CRUDBase
from sqlalchemy.orm import selectinload
from app.crud.mixins import CRUDUserFilterMixin
from app.crud.tool_crud import crud_tool
from app.crud.knowledge_crud import crud_knowledge
from app.models.base import InvokeConfig


class CRUDAgent(CRUDBase[Agent, AgentCreate, AgentUpdate], CRUDUserFilterMixin):
    """🤖 智能体 CRUD（基于通用 CRUDBase）"""

    def __init__(self):
        super().__init__(Agent)

    async def get_distinct_types_scenes(
        self, user_id: str, db_session: AsyncSession
    ) -> Tuple[List[str], List[str]]:
        """
        获取指定用户的智能体去重的 type 和 scene 列表
        """
        # ✅ 使用 distinct 提升查询效率
        type_query = await db_session.execute(
            select(distinct(Agent.type)).where(
                Agent.user_id == user_id, Agent.type.is_not(None)
            )
        )
        scene_query = await db_session.execute(
            select(distinct(Agent.scene)).where(
                Agent.user_id == user_id, Agent.scene.is_not(None)
            )
        )

        types = [t[0] for t in type_query.all() if t[0]]
        scenes = [s[0] for s in scene_query.all() if s[0]]

        return types, scenes

    async def _apply_relations_and_config(self, agent: Agent, *, tool_ids: list[str] | None, knowledge_ids: list[str] | None, db_session: AsyncSession) -> Agent:
        """根据传入的 tool_ids 和 knowledge_ids 更新 agent 的工具与知识库关系（关系表维护）。"""
        # ✅ 预加载关系，避免赋值时触发懒加载 MissingGreenlet
        agent_loaded = await self.get_with_relations(id=agent.id, relations=["tools", "knowledges"], db_session=db_session)
        agent = agent_loaded or agent

        # 更新工具关系
        if tool_ids is not None:
            tools = await crud_tool.get_by_ids(list_ids=tool_ids, db_session=db_session)
            agent.tools = tools or []
        # 更新知识库关系（不再写入 invoke_config）
        if knowledge_ids is not None:
            knows = await crud_knowledge.get_by_ids(list_ids=knowledge_ids, db_session=db_session)
            agent.knowledges = knows or []
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        return agent

    async def create_with_relations(self, *, payload: AgentCreate, db_session: AsyncSession) -> Agent:
        """创建 Agent 并根据 payload.tool_ids/knowledge_ids 维护关系与配置。"""
        # 先按基础字段创建（过滤关系字段，并映射 desc→description）
        base_data = payload.model_dump(exclude={"tool_ids", "knowledge_ids"}, exclude_unset=True)
        if "desc" in base_data:
            base_data["description"] = base_data.pop("desc")
        # 仅保留模型真实列，避免未知字段导致校验错误
        try:
            allowed_columns = set(Agent.__table__.columns.keys())
            base_data = {k: v for k, v in base_data.items() if k in allowed_columns}
        except Exception:
            pass
        agent = Agent.model_validate(base_data)
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        # 再应用关系与配置（预加载关系，避免异步会话懒加载触发 MissingGreenlet）
        agent_loaded = await self.get_with_relations(id=agent.id, relations=["tools", "knowledges"], db_session=db_session)
        return await self._apply_relations_and_config(agent_loaded or agent, tool_ids=payload.tool_ids, knowledge_ids=payload.knowledge_ids, db_session=db_session)

    async def update_with_relations(self, *, agent_id: str, payload: AgentUpdate, db_session: AsyncSession) -> Agent:
        """更新 Agent 基础字段，并维护 tool_ids/knowledge_ids。"""
        # 查当前
        agent = await self.get(id=agent_id, db_session=db_session)
        if not agent:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="智能体不存在")
        # 更新基础字段（不含关系字段），映射 desc→description 并过滤未知列
        update_data = payload.model_dump(exclude_unset=True, exclude={"tool_ids", "knowledge_ids"})
        if "desc" in update_data:
            update_data["description"] = update_data.pop("desc")
        try:
            allowed_columns = set(Agent.__table__.columns.keys())
        except Exception:
            allowed_columns = set()
        for field, value in update_data.items():
            if field not in allowed_columns:
                continue
            setattr(agent, field, value)
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        # 维护关系与配置（预加载关系，避免异步会话懒加载触发 MissingGreenlet）
        agent_loaded = await self.get_with_relations(id=agent_id, relations=["tools", "knowledges"], db_session=db_session)
        return await self._apply_relations_and_config(agent_loaded or agent, tool_ids=payload.tool_ids, knowledge_ids=payload.knowledge_ids, db_session=db_session)
    
# ✅ 单例实例
crud_agent = CRUDAgent()
