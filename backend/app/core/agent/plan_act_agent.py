"""
Plan → Act → Reflect → Verify → Memory
工程级 Agent 框架集成（支持动态重规划 Dynamic Re-Planning）

适配本项目：
- 统一 LLM 接入：复用 app.core.model.model_service，构建 LangChain Chat 模型（OpenAI/Azure）
- 工具体系：复用 ToolLoader，加载 LangChain BaseTool/StructuredTool，并在 Act 阶段动态调用
- Episode 记忆：使用 Pydantic 数据结构，支持序列化为 JSON
- 异步化：所有 LLM/工具调用使用异步接口，便于在 FastAPI 端点中调用
- 动态规划：根据每步执行结果与反思，决定是否触发 Re-Plan，重新生成后续计划

使用示例：
    from app.core.agent.plan_act_agent import PlanActAgent
    agent = PlanActAgent(agent_obj=db_agent, user_id="u123")
    result = await agent.run(task="如果我有 15 个苹果，吃掉 4 个，再乘以 3，有多少个？")

返回：最终答案字符串，同时可通过 agent.memory 获取完整 episode 轨迹。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from langchain_openai import ChatOpenAI, AzureChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field  # Field 目前未用到，但保留以便之后扩展

from app.services.model_service import model_service
from app.core.tool.tool_loader import ToolLoader
from app.models.agent import Agent as AgentModel

logger = logging.getLogger(__name__)


# ============================================================
# 数据结构：ToolCall / StepResult / EpisodeMemory
# ============================================================

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


# ============================================================
# Agent 状态机
# ============================================================

class AgentState:
    PLAN = "plan"
    ACT = "act"
    REFLECT = "reflect"
    VERIFY = "verify"
    FINISH = "finish"


# ============================================================
# 统一 LLM 客户端（基于项目的模型/凭证）
# ============================================================

class LLMContext(BaseModel):
    provider_label: Optional[str] = None
    model_name: Optional[str] = None


class LLMClient:
    """根据 Agent 配置与用户凭证构建 LangChain Chat 模型。
    与 AgentRunner 使用相同逻辑，避免环境变量依赖。
    """

    def __init__(self, agent_obj: AgentModel, user_id: str):
        self.agent_obj = agent_obj
        self.user_id = user_id
        self.llm: ChatOpenAI | AzureChatOpenAI | None = None
        self.ctx = LLMContext()

    async def init(self) -> None:
        agent_obj = self.agent_obj

        # 解析模型调用配置
        raw_cfg = getattr(agent_obj, "invoke_config", None) or getattr(agent_obj.model, "invoke_config", None)
        cfg = model_service.coerce_invoke_config(raw_cfg)

        # 模型名称
        if isinstance(raw_cfg, dict):
            model_name = raw_cfg.get("name") or getattr(agent_obj.model, "invoke_config", {}).get("name", "gpt-4o")
        else:
            model_name = getattr(cfg, "name", None) or "gpt-4o"
        self.ctx.model_name = model_name

        # provider 判定（自动识别 Azure 风格）
        prov = getattr(agent_obj.model, "provider", None)
        if not prov:
            base_url_candidate = None
            try:
                base_url_candidate = cfg.client.base_url if (cfg and getattr(cfg, "client", None)) else None
            except Exception:
                base_url_candidate = None
            if base_url_candidate:
                bu = base_url_candidate.lower()
                if "cognitiveservices.azure.com" in bu or "/openai/deployments/" in bu:
                    prov = "azure"
        if not prov:
            prov = "openai"
        p_lower = prov.lower()
        self.ctx.provider_label = (
            "AzureOpenAI" if p_lower in ("azure", "azure-openai") else (
                "OpenAI" if p_lower in ("openai", "oai", "openai-compatible") else prov
            )
        )

        # 读取凭证
        creds = await model_service.get_provider_credentials(
            user_id=str(getattr(agent_obj, "user_id", "") or self.user_id),
            provider=prov,
            reveal_secret=True,
        )

        # 采样参数
        temperature = 0.7
        max_completion_tokens: Optional[int] = None
        try:
            if cfg and getattr(cfg, "parameters", None) and cfg.parameters.temperature is not None:
                temperature = float(cfg.parameters.temperature)
            if cfg and getattr(cfg, "parameters", None) and cfg.parameters.max_completion_tokens is not None:
                max_completion_tokens = int(cfg.parameters.max_completion_tokens)
        except Exception:
            pass

        # 构建 LLM
        if p_lower in ("azure", "azure-openai"):
            api_key = creds.get("api_key")
            azure_endpoint = creds.get("azure_endpoint") or (cfg.client.azure_endpoint if getattr(cfg, "client", None) else None)
            if azure_endpoint:
                azure_endpoint = model_service.derive_azure_endpoint(azure_endpoint)
            api_version = creds.get("api_version") or (cfg.client.api_version if getattr(cfg, "client", None) else None)
            deployment_name = creds.get("azure_deployment") or model_name
            if not api_key or not azure_endpoint or not api_version:
                raise ValueError("Missing Azure credentials (api_key/endpoint/api_version)")
            try:
                self.llm = AzureChatOpenAI(
                    api_key=api_key,
                    azure_endpoint=azure_endpoint,
                    api_version=api_version,
                    azure_deployment=deployment_name,
                    temperature=temperature,
                    max_completion_tokens=max_completion_tokens,
                )
            except TypeError:
                # 某些版本使用 model 字段
                self.llm = AzureChatOpenAI(
                    api_key=api_key,
                    azure_endpoint=azure_endpoint,
                    api_version=api_version,
                    model=deployment_name,
                    temperature=temperature,
                    max_completion_tokens=max_completion_tokens,
                )
        elif p_lower in ("openai", "oai", "openai-compatible"):
            api_key = creds.get("api_key")
            base_url = creds.get("base_url") or (cfg.client.base_url if getattr(cfg, "client", None) else None)
            organization = creds.get("organization") or (cfg.client.organization if getattr(cfg, "client", None) else None)
            if not api_key:
                raise ValueError("Missing provider API key")
            self.llm = ChatOpenAI(
                model=model_name,
                api_key=api_key,
                base_url=base_url,
                organization=organization,
                temperature=temperature,
                max_completion_tokens=max_completion_tokens,
            )
        else:
            raise ValueError(f"Unsupported provider: {prov}")

    async def call(self, system: str, prompt: str, tools: Optional[List[BaseTool]] = None) -> Any:
        """统一 LLM 调用接口。
        - 返回 LangChain 的 AIMessage 对象（可能包含 tool_calls）
        """
        if not self.llm:
            raise RuntimeError("LLM not initialized")
        msgs = [SystemMessage(content=system), HumanMessage(content=prompt)]
        try:
            if tools:
                llm_with_tools = self.llm.bind_tools(tools)
                return await llm_with_tools.ainvoke(msgs)
            return await self.llm.ainvoke(msgs)
        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            raise


# ============================================================
# PlanActAgent 主体（支持动态 Re-Planning）
# ============================================================

class PlanActAgent:
    """主 Agent（重点：ACT 阶段支持 OpenAI Tool Calling + 动态重规划）"""

    def __init__(self, agent_obj, user_id: str):
        self.agent_obj = agent_obj
        self.user_id = user_id
        self.llm_client = LLMClient(agent_obj=agent_obj, user_id=user_id)
        self.tools: Dict[str, BaseTool] = {}
        self.tool_list: List[BaseTool] = []
        self.state = AgentState.PLAN
        self.current_step_index = 0
        self.memory = EpisodeMemory(task="")
        self.extra_context: Dict[str, Any] = {}

    async def _init(self):
        await self.llm_client.init()

        # 加载 Agent 绑定的工具
        tools_records = getattr(self.agent_obj, "tools", []) or []
        loaded_tools = ToolLoader.load_tools_from_records(tools_records)

        # 若 Agent 未绑定工具 → 加载系统默认工具
        if not loaded_tools:
            try:
                for name in ToolLoader.get_loaded_tools():
                    obj = ToolLoader._load_tool_by_name(name)
                    if obj:
                        loaded_tools.append(obj)
            except Exception as e:
                logger.error(f"加载默认工具异常: {e}")

        # 构建 tool 映射
        self.tools = {t.name: t for t in loaded_tools}
        self.tool_list = list(self.tools.values())
        logger.info(f"🧰 加载工具: {list(self.tools.keys())}")

    # =============================
    # 入口函数
    # =============================

    async def run(self, task: str, extra_context: Optional[Dict[str, Any]] = None):
        self.memory.task = task
        self.extra_context = extra_context or {}

        await self._init()

        while self.state != AgentState.FINISH:
            if self.state == AgentState.PLAN:
                await self._do_plan()
            elif self.state == AgentState.ACT:
                await self._do_act_tool_calling()
            elif self.state == AgentState.REFLECT:
                await self._do_reflect()
            elif self.state == AgentState.VERIFY:
                await self._do_verify()
            else:
                raise RuntimeError(f"Unknown state {self.state}")

        return self.memory.final_answer or ""

    # =============================
    # PLAN 阶段（初始规划）
    # =============================

    async def _do_plan(self):
        # -------------------------------------------------------
        # 1. 构建工具说明（传给 Planner）
        # -------------------------------------------------------
        tool_desc_list = []
        for t in self.tool_list:
            schema = {}
            if hasattr(t, "args_schema") and t.args_schema:
                try:
                    schema = t.args_schema.schema().get("properties", {})
                except Exception:
                    schema = {}

            tool_desc_list.append(
                f"- 工具名: {t.name}\n"
                f"  描述: {t.description or '无描述'}\n"
                f"  参数: {json.dumps(schema, ensure_ascii=False)}"
            )
        tool_description_text = "\n".join(tool_desc_list) if tool_desc_list else "（无工具可用）"

        # -------------------------------------------------------
        # 2. Planner System 模板（保持你给的内容 + 自动注入工具）
        # -------------------------------------------------------
        system = f"""
你是一个智能体的“任务规划模块”（Planner）。
你的职责是将用户任务拆分成最简洁、可执行的动作步骤列表（plan）。

请严格遵守以下规则：

【核心目标】
- 生成一个可执行动作（action）序列，使整个任务得以完成。
- 每个步骤都必须是“可执行行为（可被 Act 阶段执行）”。

【步骤规则】
1. 步骤必须是“行动（action）”，不能是“描述（description）”或“判断（check）”。
2. 禁止生成工具不会执行的行为，如：
   - “确认输入是否正确”
   - “判断结果是否合理”
   - “解释步骤意义”
3. 工具调用必须成为单独步骤：
   格式示例：“调用 <tool_name> 工具，并传入必要参数以完成 <具体目标>”。
4. 不要把错误处理写入 plan（错误由 Reflect/RePlan 阶段处理）。
5. 不要生成最终输出步骤（最终输出由 Verify 阶段负责）。
6. 计划必须尽可能短，只包含“必要步骤”。
7. 计划必须是 JSON 数组格式，如：
   ["step1", "step2", "step3"]

【工具使用规则】
- 你必须参考下面提供的工具列表（如存在工具）。
- 若任务可以通过某个工具完成，应优先使用该工具。
- 若任务无需工具，可以提供纯动作步骤。
- 不要推测工具不存在的功能。

【禁止事项】
- 禁止输出与执行无关的解释或说明。
- 禁止生成逻辑判断（if/else）、错误建议、总结类句子。
- 不要输出非 JSON 的任何文本。

【可用工具列表】（请严格参考）
{tool_description_text}

请基于以上规则，为以下用户任务生成最优动作计划（steps list）。
        """.strip()

        # -------------------------------------------------------
        # 3. 用户 prompt
        # -------------------------------------------------------
        prompt = f"任务：{self.memory.task}\n请直接给出 JSON 数组。"

        print("🟦 PLAN 阶段 system:")
        print(system)
        print("🟦 PLAN 阶段 prompt:")
        print(prompt)

        # -------------------------------------------------------
        # 4. 调用 LLM（Planner 不绑定工具）
        # -------------------------------------------------------
        msg = await self.llm_client.call(system, prompt, tools=None)

        print("🟩 PLAN 阶段 LLM 输出:")
        print(msg.content)

        # -------------------------------------------------------
        # 5. 解析 JSON
        # -------------------------------------------------------
        raw = (msg.content or "").strip()
        try:
            plan = json.loads(raw)
            if isinstance(plan, list):
                self.memory.plan = plan
            else:
                print("❌ Planner 未返回 JSON 数组格式")
        except Exception as e:
            print("❌ PLAN JSON 解析失败:", e)
            self.memory.plan = []

        print("🟨 生成 PLAN:", self.memory.plan)

        self.state = AgentState.ACT


    # =============================
    # 动态规划（用于 Re-Plan）
    # =============================

    async def _dynamic_plan(self) -> List[str]:
        """动态规划：根据历史执行结果重新生成后续计划。"""
        history_text = "\n".join(
            f"[{i}] step={r.step}, result={r.tool_result}, reflection={r.reflection}"
            for i, r in enumerate(self.memory.step_results)
        )

        tool_desc_list = []
        for t in self.tool_list:
            schema = t.args_schema.schema() if hasattr(t, "args_schema") else {}
            tool_desc_list.append(
                f"工具名: {t.name}\n"
                f"描述: {t.description or ''}\n"
                f"参数: {json.dumps(schema.get('properties', {}), ensure_ascii=False)}"
            )
        tool_description_text = "\n\n".join(tool_desc_list)

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

        msg = await self.llm_client.call(system, prompt)

        try:
            new_plan = json.loads(msg.content)
            if not isinstance(new_plan, list):
                raise ValueError("PLAN 必须为 list")
            return new_plan
        except Exception as e:
            print("Dynamic PLAN JSON 解析失败:", e)
            return []

    # =============================
    # ACT：工具自动调用
    # =============================

    async def _do_act_tool_calling(self):
        if self.current_step_index >= len(self.memory.plan):
            self.state = AgentState.VERIFY
            return

        step = self.memory.plan[self.current_step_index]

        print("\n==============================")
        print(f"▶️ ACT 阶段：执行 step[{self.current_step_index}]: {step}")
        print("==============================")

        # 历史记录（用于上下文）
        history = "\n".join(
            f"[{i}] step={r.step}, result={r.tool_result}"
            for i, r in enumerate(self.memory.step_results)
        )

        system = "You are an intelligent agent executor. You may call tools."

        prompt = (
            f"历史执行记录：\n{history}\n\n"
            f"当前步骤：{step}\n"
            f"如需调用工具，请直接调用工具；不需要时给出文本结果。"
        )

        print("🟦 ACT system:")
        print(system)
        print("🟦 ACT prompt:")
        print(prompt)

        ai = await self.llm_client.call(system, prompt, self.tool_list)

        print("🟩 ACT LLM 输出:")
        print("content:", ai.content)
        print("tool_calls:", getattr(ai, "tool_calls", None))

        step_result = StepResult(step=step)

        # 辅助：提取某工具的 secure 字段集合（用于打印时屏蔽敏感值）
        def _extract_secure_fields(t: BaseTool):
            secure_fields = set()
            try:
                schema = t.args_schema.schema() if hasattr(t, "args_schema") and t.args_schema else {}
                props = schema.get("properties", {})
                for fname, fdef in props.items():
                    extra = fdef.get("json_schema_extra") or {}
                    if extra.get("secure") is True:
                        secure_fields.add(fname)
            except Exception:
                pass
            return secure_fields

        # 检测函数签名中被 Annotated[..., InjectedToolArg] 标注的参数名
        import inspect
        from typing import get_origin, get_args
        from pydantic import BaseModel as _PydanticBaseModel
        from langchain_core.tools.base import InjectedToolArg as _InjectedToolArg

        def _get_injected_params(t: BaseTool):
            injected: dict[str, inspect.Parameter] = {}
            try:
                fn = getattr(t, "func", None) or getattr(t, "coroutine", None)
                if not fn:
                    return injected
                sig = inspect.signature(fn)
                for name, p in sig.parameters.items():
                    anno = p.annotation
                    if get_origin(anno) is not None and str(get_origin(anno)) == str(get_origin(get_args(anno)[0])):
                        # 防御：避免误判复杂 typing 场景
                        pass
                    if get_origin(anno) is not Annotated:
                        continue
                    ann_args = get_args(anno)
                    if len(ann_args) < 2:
                        continue
                    # 约定：Annotated[<real_type>, InjectedToolArg]
                    marker = ann_args[-1]
                    if marker is _InjectedToolArg:
                        injected[name] = p
                    else:
                        # 某些实现使用 _DirectlyInjectedToolArg 或子类
                        try:
                            from langchain_core.tools.base import _DirectlyInjectedToolArg as _DI
                            if isinstance(marker, type) and issubclass(marker, _DI):
                                injected[name] = p
                        except Exception:
                            pass
            except Exception:
                pass
            return injected

        def _build_injected_value(p: inspect.Parameter, raw_val):
            if raw_val is None:
                return None
            anno = p.annotation
            base_type = None
            if get_origin(anno) is Annotated:
                ann_args = get_args(anno)
                real = ann_args[0]
                # Optional[T] or Union[T, None]
                if get_origin(real) in (Optional, __import__('typing').Union):
                    uargs = [a for a in get_args(real) if a is not type(None)]  # noqa: E721
                    base_type = uargs[0] if uargs else None
                else:
                    base_type = real
            try:
                if isinstance(raw_val, dict) and isinstance(base_type, type) and issubclass(base_type, _PydanticBaseModel):
                    return base_type(**raw_val)
            except Exception:
                pass
            return raw_val

        def _mask_secure(data: Dict[str, Any], secs: set[str]) -> Dict[str, Any]:
            masked = dict(data or {})
            for k in secs:
                if k in masked and masked[k] is not None:
                    masked[k] = "***"
            return masked

        # 若 LLM 调用了工具
        tool_calls = getattr(ai, "tool_calls", None)
        if tool_calls:
            call = tool_calls[0]
            tool_name = call["name"]
            args = call["args"]
            tool_obj = self.tools[tool_name]

            # 运行时参数注入：根据函数签名中 Annotated[..., InjectedToolArg] 的参数进行注入
            secure_fields = _extract_secure_fields(tool_obj)
            injected_params = _get_injected_params(tool_obj)

            runtime_params_all = None
            if isinstance(self.extra_context, dict):
                runtime_params_all = self.extra_context.get("runtime_params") or self.extra_context.get("form_params") or {}
            runtime_params_for_tool = runtime_params_all.get(tool_name, {}) if isinstance(runtime_params_all, dict) else {}

            real_args = dict(args or {})
            for name, p in injected_params.items():
                # 优先取按工具名分组的注入值，其次取全局 extra_context 同名值
                raw_val = None
                if isinstance(runtime_params_for_tool, dict) and name in runtime_params_for_tool:
                    raw_val = runtime_params_for_tool[name]
                elif isinstance(self.extra_context, dict) and name in self.extra_context:
                    raw_val = self.extra_context[name]
                val = _build_injected_value(p, raw_val)
                if val is not None:
                    real_args[name] = val

            masked_args = _mask_secure(real_args, secure_fields)
            if "auth" in masked_args:
                masked_args["auth"] = "***"

            print(f"🛠️ 调用工具: {tool_name}")
            print(f"参数(已屏蔽敏感): {masked_args}")

            # 记录到 EpisodeMemory 时使用屏蔽后的参数
            step_result.tool_call = ToolCall(tool=tool_name, args=masked_args)

            try:
                tool_res = await tool_obj.ainvoke(real_args)
                print(f"🔧 工具返回: {tool_res}")
            except Exception as e:
                tool_res = f"TOOL_ERROR: {str(e)}"
                print(f"❌ 工具报错: {tool_res}")

            step_result.tool_result = f"调用工具{tool_name}工具返回：" + str(tool_res)

        else:
            # 纯文本输出
            print("💬 LLM 未调用工具，直接输出文本结果")
            step_result.reasoning = ai.content
            step_result.tool_result = ai.content

        self.memory.step_results.append(step_result)
        self.state = AgentState.REFLECT

    # =============================
    # 判断是否需要 Re-Plan
    # =============================

    async def _maybe_replan(self, last_step: StepResult) -> bool:
        """判断是否需要重规划。
        触发 re-plan 的典型条件：
        1. 工具错误
        2. 反思表明执行失败
        """

        # 情况 1：工具调用错误
        if isinstance(last_step.tool_result, str) and "TOOL_ERROR" in last_step.tool_result:
            return True

        # 情况 2：LLM reflection 表示失败（简单关键词触发，可按需扩展）
        if last_step.reflection and any(
            k in last_step.reflection.lower()
            for k in ["失败", "不正确", "错误", "无法执行", "未达成", "not correct", "failed", "error"]
        ):
            return True

        # TODO: 可进一步扩展例如：连续多步无效输出、结果重复等情况
        return False

    # =============================
    # REFLECT（带动态重规划）
    # =============================

    async def _do_reflect(self):
        last = self.memory.step_results[-1]

        print("\n🧠 ENTER REFLECT 阶段")
        print("反思对象步骤:", last.step)
        print("执行结果:", last.tool_result)

        # ---------- 反思 LLM ----------
        system = (
            "你是一个反思模块，请分析步骤执行结果。\n"
            "输出 JSON：{\n"
            "  \"summary\": \"对执行质量的一句话评价\",\n"
            "  \"is_complete\": true/false,  // 是否已完全满足用户任务\n"
            "  \"need_replan\": true/false   // 若未完成任务，是否需要重新规划\n"
            "}"
        )
        prompt = (
            f"用户任务：{self.memory.task}\n"
            f"当前步骤：{last.step}\n"
            f"执行结果：{last.tool_result}\n"
            "请按 JSON 格式回答。"
        )

        msg = await self.llm_client.call(system, prompt)
        print("🟣 REFLECT 输出:", msg.content)

        # ---------- 解析反思 JSON ----------
        try:
            ref = json.loads(msg.content)
        except:
            ref = {"summary": msg.content, "is_complete": False, "need_replan": False}

        last.reflection = ref.get("summary", "反思失败")

        is_complete = ref.get("is_complete", False)
        need_replan = ref.get("need_replan", False)

        # =================================================
        # 🟢 Case 1: 已完成用户整体任务 → 直接进入 VERIFY
        # =================================================
        if is_complete:
            print("🎉 反思认为：任务已经完成，跳过剩余 plan，进入 VERIFY")
            self.memory.plan = []    # 清空计划
            self.state = AgentState.VERIFY
            return

        # =================================================
        # 🟡 Case 2: 未完成任务，但反思认为需要 Re-Plan
        # =================================================
        if need_replan:
            print("🔄 反思认为：需要重新规划！开始生成新计划")
            new_plan = await self._dynamic_plan()

            print("🔄 旧 plan:", self.memory.plan)
            print("🔄 新 plan:", new_plan)

            # 替换 plan 并从头执行
            self.memory.plan = new_plan
            self.current_step_index = 0
            self.state = AgentState.ACT
            return

        # =================================================
        # 🔵 Case 3: 正常继续下一步
        # =================================================
        self.current_step_index += 1
        self.state = AgentState.ACT if self.current_step_index < len(self.memory.plan) else AgentState.VERIFY


    # =============================
    # VERIFY（最终答案生成）
    # =============================

    async def _do_verify(self):
        print("\n🔍 VERIFY 阶段")
        print("📝 EpisodeMemory:")
        print(self.memory.to_json())

        system = (
            "You are a final verifier. "
            "Output only JSON: {\"pass\": true/false, \"answer\": \"根据执行结果，回答用户的问题\"}."
        )
        prompt = self.memory.to_json()

        msg = await self.llm_client.call(system, prompt, tools=None)
        raw = msg.content or ""

        print("🟩 VERIFY LLM 输出:", raw)

        try:
            data = json.loads(raw)
            self.memory.final_answer = data.get("answer", "")
            self.memory.verified = bool(data.get("pass", False))
        except Exception:
            self.memory.final_answer = raw
            self.memory.verified = False

        print(f"🎉 FINAL ANSWER: {self.memory.final_answer}")
        print(f"✔ verified: {self.memory.verified}")

        self.state = AgentState.FINISH
