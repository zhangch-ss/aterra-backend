from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Any, List, Optional, Dict

from app.api.deps import get_db
from app.crud.agent_crud import crud_agent
from app.core.agent.plan_act_agent import PlanActAgent

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

    # 执行 Episode
    plan_agent = PlanActAgent(agent_obj=agent_obj, user_id=payload.user_id)

    final_answer = await plan_agent.run(
        task=payload.task,
        extra_context={
            "runtime_params": payload.runtime_params or payload.form_params or {},
            "user_id": payload.user_id,
        }
    )

    # 组装响应
    mem = plan_agent.memory
    model_info = {
        "model_id": getattr(plan_agent.llm_client.ctx, "model_name", None),
        "provider": getattr(plan_agent.llm_client.ctx, "provider_label", None),
    }
    resp = PlanActRunResponse(
        ok=True,
        final_answer=final_answer,
        verified=bool(mem.verified),
        plan=mem.plan,
        step_results=[sr.model_dump(exclude_none=True) for sr in mem.step_results],
        model_info=model_info,
        memory_json=mem.to_json() if (payload.return_memory is True) else None,
    )
    return resp
