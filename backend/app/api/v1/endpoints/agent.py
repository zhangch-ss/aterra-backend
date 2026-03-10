# app/api/agent.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, get_current_user
from app.crud.agent_crud import crud_agent
from app.schemas.agent import AgentCreate, AgentUpdate, AgentOut, AgentRead

router = APIRouter()

@router.get("", response_model=list[AgentRead])
async def list_agents(
    type: str | None = None,
    scene: str | None = None,
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    agents = await crud_agent.get_by_user_id(
        user_id=current_user.id, type=type, scene=scene, keyword=keyword, db_session=db
    )
    # ✅ 统一做 model_validate
    return [AgentRead.model_validate(a, from_attributes=True) for a in agents]

@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(agent_id: str, db: AsyncSession = Depends(get_db), current_user = Depends(get_current_user)):
    # ✅ relations 包含工具/知识库/子代理/模型
    agent = await crud_agent.get_with_relations(
        id=agent_id, relations=["tools", "knowledges", "subagents", "model"], db_session=db
    )
    if not agent:
        raise HTTPException(status_code=404, detail="智能体不存在")
    # 权限校验：仅允许访问自己的智能体
    if str(agent.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="无权限访问该智能体")
    return AgentOut.model_validate(agent, from_attributes=True)

@router.post("", response_model=AgentRead)
async def create_agent(payload: AgentCreate, db: AsyncSession = Depends(get_db), current_user = Depends(get_current_user)):
    # 使用扩展方法：创建后维护 tool_ids 与 knowledge_ids
    # 由服务端绑定当前用户为创建者，payload 中不再需要 user_id
    new_agent = await crud_agent.create_with_relations(payload=payload, user_id=str(current_user.id), db_session=db)
    return AgentRead.model_validate(new_agent, from_attributes=True)

@router.put("/{agent_id}", response_model=AgentOut)
async def update_agent(agent_id: str, payload: AgentUpdate, db: AsyncSession = Depends(get_db), current_user = Depends(get_current_user)):
    # 使用扩展方法：更新基础字段并维护 tool_ids 与 knowledge_ids
    # 越权检查
    db_agent = await crud_agent.get(id=agent_id, db_session=db)
    if not db_agent:
        raise HTTPException(status_code=404, detail="智能体不存在")
    if str(db_agent.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="无权限修改该智能体")
    updated = await crud_agent.update_with_relations(agent_id=agent_id, payload=payload, db_session=db)
    # 重新加载带关系的对象返回
    full = await crud_agent.get_with_relations(
        id=agent_id, relations=["tools", "knowledges", "subagents", "model"], db_session=db
    )
    return AgentOut.model_validate(full, from_attributes=True)

@router.delete("/{agent_id}", response_model=dict)
async def delete_agent(agent_id: str, db: AsyncSession = Depends(get_db), current_user = Depends(get_current_user)):
    db_agent = await crud_agent.get(id=agent_id, db_session=db)
    if not db_agent:
        raise HTTPException(status_code=404, detail="智能体不存在")
    if str(db_agent.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="无权限删除该智能体")
    await crud_agent.remove(id=agent_id, db_session=db)
    return {"ok": True}
