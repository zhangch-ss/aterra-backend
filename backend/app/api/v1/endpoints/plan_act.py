from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Any, List, Optional, Dict

from app.api.deps import get_db
from app.crud.agent_crud import crud_agent
from app.core.agent.base import AgentContext
from app.core.agent.registry import AgentRegistry
from app.core.agent.types import plan_act as _plan_act_module  # noqa: F401 触发注册

router = APIRouter()


class PlanActRunRequest(BaseModel):
    task: str
    user_id: str
    return_memory: bool | None = True
    # 可选：运行时注入的工具参数（按工具名分组）
    runtime_params: Optional[Dict[str, Dict[str, Any]]] = None
    # 兼容旧字段：form_params（将被 runtime_params 替代）
    form_params: Optional[Dict[str, Dict[str, Any]]] = None


class PlanActRunResponse(BaseModel):
    ok: bool
    final_answer: str
    verified: bool
    plan: List[str] | None = None
    step_results: List[dict] | None = None
    model_info: dict[str, Any] | None = None
    memory_json: str | None = None


@router.post("/{agent_id}/plan-act/run", response_model=PlanActRunResponse)
async def run_plan_act(agent_id: str, payload: PlanActRunRequest, db: AsyncSession = Depends(get_db)):
    """运行 Plan→Act→Reflect→Verify→Memory agent 流程，并返回最终答案与可选的 episode 轨迹。"""
    # 加载 Agent（带模型与工具关系）
    agent_obj = await crud_agent.get_with_relations(
        id=agent_id,
        relations=["model", "tools"],
        db_session=db,
    )
    if not agent_obj:
        raise HTTPException(status_code=404, detail="智能体不存在")

    # 基于通用框架：Registry 创建 planact 实现，并直接调用 run
    agent_impl = AgentRegistry.create(agent_obj, db, kind="planact")
    ctx = AgentContext(
        user_id=payload.user_id,
        db=db,
        extra_context={
            "runtime_params": payload.runtime_params or payload.form_params or {},
            "user_id": payload.user_id,
            "task": payload.task,
        },
    )
    final_answer = await agent_impl.run(task=payload.task, context=ctx)

    # 组装响应（从实现获取模型信息与记忆轨迹）
    mem = getattr(agent_impl, "memory", None)
    model_info = getattr(agent_impl, "get_model_info", None)
    model_info = model_info() if callable(model_info) else {}
    resp = PlanActRunResponse(
        ok=True,
        final_answer=final_answer,
        verified=bool(getattr(mem, "verified", False)),
        plan=getattr(mem, "plan", []),
        step_results=[sr.model_dump(exclude_none=True) for sr in getattr(mem, "step_results", [])],
        model_info=model_info,
        memory_json=(mem.to_json() if (payload.return_memory is True and hasattr(mem, "to_json")) else None),
    )
    return resp
