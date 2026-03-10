from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from app.core.agent.base import BaseAgent, AgentContext
from app.core.agent.llm_client import LLMClient
from app.core.agent.tools import ToolManager
from app.models.agent import Agent as AgentModel
from app.core.agent.streaming import AgentEmit, run_tool_with_events, stream_llm_phase
from app.core.prompts.prompts import PLAN_ACT_TASK_TEMPLATE, TOOL_CALL_TEMPLATE, REFLECTION_TEMPLATE, VERIFY_TEMPLATE

logger = logging.getLogger(__name__)


class ToolCall(BaseModel):
    tool: str
    args: Dict[str, Any]


class StepResult(BaseModel):
    step: str
    tool_call: Optional[ToolCall] = None
    tool_result: Optional[Any] = None
    reasoning: Optional[str] = None
    reflection: Optional[str] = None


class EpisodeMemory(BaseModel):
    task: str
    plan: List[str] = []
    step_results: List[StepResult] = []
    final_answer: Optional[str] = None
    verified: bool = False

    def to_json(self) -> str:
        return self.model_dump_json(ensure_ascii=False, indent=2)


class AgentState:
    PLAN = "plan"
    ACT = "act"
    REFLECT = "reflect"
    VERIFY = "verify"
    FINISH = "finish"


class PlanActAdapter(BaseAgent):
    """将工程版 Plan→Act→Reflect→Verify Agent 改造成 BaseAgent 实现。

    - run(task, context) 返回最终答案，memory 记录完整轨迹
    - astream(history, context) 简单地按 token 事件输出最终答案（当前端点不需要 SSE，可作为占位）
    """

    def __init__(self, agent_obj: AgentModel, db: AsyncSession):
        self.agent_obj = agent_obj
        self.db = db
        self.llm_client: Optional[LLMClient] = None
        self.tools: Dict[str, BaseTool] = {}
        self.tool_list: List[BaseTool] = []
        self.state = AgentState.PLAN
        self.current_step_index = 0
        self.memory = EpisodeMemory(task="")
        self.provider_label = None
        self.model_name = None

    async def _init(self, user_id: str):
        # 统一 LLM 初始化
        self.llm_client, ctx = await LLMClient.from_agent(self.agent_obj, user_id)
        self.provider_label = ctx.provider_label
        self.model_name = ctx.model_name

        # 统一工具加载（支持默认工具回退）
        tools_records = getattr(self.agent_obj, "tools", []) or []
        loaded_tools = ToolManager.load_from_records(tools_records, include_defaults=True)
        self.tools = {t.name: t for t in loaded_tools}
        self.tool_list = list(self.tools.values())

    async def _do_plan(self):
        tool_description_text = ToolManager.describe_tools(self.tool_list)
        # 使用统一模板
        system = PLAN_ACT_TASK_TEMPLATE.format(tool_description=tool_description_text)

        prompt = f"任务：{self.memory.task}\n请直接给出 JSON 数组。"
        msg = await self.llm_client.llm.ainvoke([SystemMessage(content=system), HumanMessage(content=prompt)])
        raw = (msg.content or "").strip()
        try:
            plan = json.loads(raw)
            if isinstance(plan, list):
                self.memory.plan = plan
            else:
                self.memory.plan = []
        except Exception:
            self.memory.plan = []
        self.state = AgentState.ACT

    async def _do_act_tool_calling(self, extra_context: Optional[Dict[str, Any]] = None):
        if self.current_step_index >= len(self.memory.plan):
            self.state = AgentState.VERIFY
            return
        step = self.memory.plan[self.current_step_index]
        history = "\n".join(
            f"[{i}] step={r.step}, result={r.tool_result}" for i, r in enumerate(self.memory.step_results)
        )
        # 使用统一工具调用模板
        system = TOOL_CALL_TEMPLATE
        prompt = (
            f"历史执行记录：\n{history}\n\n"
            f"当前步骤：{step}\n"
            f"如需调用工具，请直接调用工具；不需要时给出文本结果。"
        )
        llm_with_tools = self.llm_client.llm.bind_tools(self.tool_list) if self.tool_list else self.llm_client.llm
        ai = await llm_with_tools.ainvoke([SystemMessage(content=system), HumanMessage(content=prompt)])

        step_result = StepResult(step=step)

        # 参数注入与脱敏
        tool_calls = getattr(ai, "tool_calls", None)
        if tool_calls:
            call = tool_calls[0]
            tool_name = call["name"]
            args = call["args"]
            tool_obj = self.tools[tool_name]
            real_args, masked_args = ToolManager.prepare_args(tool_obj, args, extra_context)
            step_result.tool_call = ToolCall(tool=tool_name, args=masked_args)
            try:
                tool_res = await tool_obj.ainvoke(real_args)
            except Exception as e:
                tool_res = f"TOOL_ERROR: {str(e)}"
            step_result.tool_result = f"调用工具{tool_name}工具返回：" + str(tool_res)
        else:
            step_result.reasoning = ai.content
            step_result.tool_result = ai.content

        self.memory.step_results.append(step_result)
        self.state = AgentState.REFLECT

    async def _dynamic_plan(self) -> List[str]:
        history_text = "\n".join(
            f"[{i}] step={r.step}, result={r.tool_result}, reflection={r.reflection}" for i, r in enumerate(self.memory.step_results)
        )
        tool_description_text = ToolManager.describe_tools(self.tool_list)
        system = (
            "你是一个动态任务规划器，根据已执行的步骤、执行结果和反思信息，"
            "持续更新剩余计划，以最优方式达成最终目标。\n"
            "- 不要重复已经完成的步骤\n"
            "- 只返回未来任务列表（JSON 数组形式）\n\n"
            f"可用工具：\n{tool_description_text}"
        )
        prompt = (
            f"用户任务：{self.memory.task}\n\n"
            f"已执行历史：\n{history_text}\n\n"
            "请返回后续步骤列表（JSON 数组，如 [\"stepX\", \"stepY\", ...]）。"
        )
        msg = await self.llm_client.llm.ainvoke([SystemMessage(content=system), HumanMessage(content=prompt)])
        try:
            new_plan = json.loads(msg.content or "[]")
            if not isinstance(new_plan, list):
                raise ValueError("PLAN 必须为 list")
            return new_plan
        except Exception:
            return []

    async def _maybe_replan(self, last_step: StepResult) -> bool:
        if isinstance(last_step.tool_result, str) and "TOOL_ERROR" in last_step.tool_result:
            return True
        if last_step.reflection and any(
            k in last_step.reflection.lower() for k in ["失败", "不正确", "错误", "无法执行", "未达成", "not correct", "failed", "error"]
        ):
            return True
        return False

    async def _do_reflect(self):
        last = self.memory.step_results[-1]
        prompt = (
            f"用户任务：{self.memory.task}\n"
            f"当前步骤：{last.step}\n"
            f"执行结果：{last.tool_result}\n"
            "请按 JSON 格式回答。"
        )
        msg = await self.llm_client.llm.ainvoke([SystemMessage(content=REFLECTION_TEMPLATE), HumanMessage(content=prompt)])
        try:
            ref = json.loads(msg.content or "{}")
        except Exception:
            ref = {"summary": msg.content, "is_complete": False, "need_replan": False}
        last.reflection = ref.get("summary", "反思失败")
        is_complete = ref.get("is_complete", False)
        need_replan = ref.get("need_replan", False)

        if is_complete:
            self.memory.plan = []
            self.state = AgentState.VERIFY
            return
        if need_replan:
            new_plan = await self._dynamic_plan()
            self.memory.plan = new_plan
            self.current_step_index = 0
            self.state = AgentState.ACT
            return
        self.current_step_index += 1
        self.state = AgentState.ACT if self.current_step_index < len(self.memory.plan) else AgentState.VERIFY

    async def _do_verify(self):

        prompt = self.memory.to_json()
        msg = await self.llm_client.llm.ainvoke([SystemMessage(content=VERIFY_TEMPLATE), HumanMessage(content=prompt)])
        raw = msg.content or ""
        try:
            data = json.loads(raw)
            self.memory.final_answer = data.get("answer", "")
            self.memory.verified = bool(data.get("pass", False))
        except Exception:
            self.memory.final_answer = raw
            self.memory.verified = False
        self.state = AgentState.FINISH

    async def run(self, task: str, *, context: AgentContext) -> str:
        await self._init(context.user_id)
        self.memory.task = task
        extra_ctx = context.extra_context or {}
        while self.state != AgentState.FINISH:
            if self.state == AgentState.PLAN:
                await self._do_plan()
            elif self.state == AgentState.ACT:
                await self._do_act_tool_calling(extra_context=extra_ctx)
            elif self.state == AgentState.REFLECT:
                await self._do_reflect()
            elif self.state == AgentState.VERIFY:
                await self._do_verify()
            else:
                raise RuntimeError(f"Unknown state {self.state}")
        return self.memory.final_answer or ""

    async def astream(self, history_messages: List[Dict[str, Any]], *, context: AgentContext):
        # 真实流式实现：按状态机阶段边生成边输出事件
        await self._init(context.user_id)
        extra_ctx = context.extra_context or {}
        self.memory.task = history_messages[-1].get("content", "")

        while self.state != AgentState.FINISH:
            if self.state == AgentState.PLAN:
                tool_description_text = ToolManager.describe_tools(self.tool_list)
                system = PLAN_ACT_TASK_TEMPLATE.format(tool_description=tool_description_text)

                prompt = f"任务：{self.memory.task}\n请直接给出 JSON 数组。"
                messages = [SystemMessage(content=system), HumanMessage(content=prompt)]
                phase_out: Dict[str, Any] = {}
                async for e in stream_llm_phase(self.llm_client, messages, tools=None, out=phase_out):
                    yield e
                raw = (phase_out.get("content") or "").strip()
                try:
                    plan = json.loads(raw)
                    self.memory.plan = plan if isinstance(plan, list) else []
                except Exception:
                    self.memory.plan = []
                self.current_step_index = 0
                self.state = AgentState.ACT

            elif self.state == AgentState.ACT:
                if self.current_step_index >= len(self.memory.plan):
                    self.state = AgentState.VERIFY
                    continue
                step = self.memory.plan[self.current_step_index]
                history = "\n".join(
                    f"[{i}] step={r.step}, result={r.tool_result}" for i, r in enumerate(self.memory.step_results)
                )

                prompt = (
                    f"历史执行记录：\n{history}\n\n"
                    f"当前步骤：{step}\n"
                    f"如需调用工具，请直接调用工具；不需要时给出文本结果。"
                )
                messages = [SystemMessage(content=TOOL_CALL_TEMPLATE), HumanMessage(content=prompt)]

                phase_out: Dict[str, Any] = {}
                async for e in stream_llm_phase(self.llm_client, messages, tools=self.tool_list or None, out=phase_out):
                    yield e

                step_result = StepResult(step=step)
                captured_tool_calls = phase_out.get("tool_calls")
                if captured_tool_calls:
                    call = captured_tool_calls[0]
                    tool_name = call.get("name") or call.get("tool_name")
                    args = call.get("args") or call.get("arguments") or {}
                    tool_obj = self.tools.get(tool_name) if self.tools else None
                    if tool_obj is None:
                        reasoning = phase_out.get("content") or ""
                        step_result.reasoning = reasoning
                        step_result.tool_result = reasoning
                    else:
                        real_args, masked_args = ToolManager.prepare_args(tool_obj, args, extra_ctx)
                        step_result.tool_call = ToolCall(tool=tool_name, args=masked_args)
                        events, tool_res = await run_tool_with_events(tool_obj, real_args=real_args, masked_args=masked_args)
                        for e in events:
                            yield e
                        step_result.tool_result = f"调用工具{tool_name}工具返回：" + str(tool_res)
                else:
                    reasoning = phase_out.get("content") or ""
                    step_result.reasoning = reasoning
                    step_result.tool_result = reasoning

                self.memory.step_results.append(step_result)
                self.state = AgentState.REFLECT

            elif self.state == AgentState.REFLECT:
                last = self.memory.step_results[-1]

                prompt = (
                    f"用户任务：{self.memory.task}\n"
                    f"当前步骤：{last.step}\n"
                    f"执行结果：{last.tool_result}\n"
                    "请按 JSON 格式回答。"
                )
                messages = [SystemMessage(content=REFLECTION_TEMPLATE), HumanMessage(content=prompt)]
                phase_out: Dict[str, Any] = {}
                async for e in stream_llm_phase(self.llm_client, messages, tools=None, out=phase_out):
                    yield e
                raw = phase_out.get("content") or ""
                try:
                    ref = json.loads(raw or "{}")
                except Exception:
                    ref = {"summary": raw, "is_complete": False, "need_replan": False}
                last.reflection = ref.get("summary", "反思失败")
                is_complete = ref.get("is_complete", False)
                need_replan = ref.get("need_replan", False)

                if is_complete:
                    self.memory.plan = []
                    self.state = AgentState.VERIFY
                    continue
                if need_replan:
                    new_plan = await self._dynamic_plan()
                    self.memory.plan = new_plan
                    self.current_step_index = 0
                    self.state = AgentState.ACT
                    continue
                self.current_step_index += 1
                self.state = AgentState.ACT if self.current_step_index < len(self.memory.plan) else AgentState.VERIFY

            elif self.state == AgentState.VERIFY:

                prompt = self.memory.to_json()
                messages = [SystemMessage(content=VERIFY_TEMPLATE), HumanMessage(content=prompt)]
                phase_out: Dict[str, Any] = {}
                async for e in stream_llm_phase(self.llm_client, messages, tools=None, out=phase_out):
                    yield e
                raw = phase_out.get("content") or ""
                try:
                    data = json.loads(raw)
                    final_answer = data.get("answer", "")
                    verified = bool(data.get("pass", False))
                except Exception:
                    final_answer = raw
                    verified = False
                self.memory.final_answer = final_answer
                self.memory.verified = verified
                # 产出最终 assistant 消息
                yield AgentEmit.assistant(final_answer)
                self.state = AgentState.FINISH

            else:
                raise RuntimeError(f"Unknown state {self.state}")


def _register() -> None:
    from app.core.agent.registry import AgentRegistry

    def factory(agent_obj: AgentModel, db: AsyncSession) -> BaseAgent:
        return PlanActAdapter(agent_obj, db)

    AgentRegistry.register("planact", factory)


_register()
