from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend

from app.core.agent.base import AgentEvent, BaseAgent, AgentContext
from app.core.agent.llm_client import LLMClient
from app.core.agent.tools import ToolManager
from app.core.config import settings
from app.core.tool.tools.gee.authz import RuntimeContext
from app.models.agent import Agent as AgentModel


class DeepAgentAdapter(BaseAgent):
    """将 deepagents 封装为统一 BaseAgent 接口，产出 AgentEvent。"""

    def __init__(self, agent_obj: AgentModel, db: AsyncSession):
        self.agent_obj = agent_obj
        self.db = db
        self._deep_agent = None
        self.provider_label = None
        self.model_name = None
        self._tools = []

    async def _init(self) -> None:
        # LLM
        raw_cfg = getattr(self.agent_obj, "invoke_config", None) or getattr(self.agent_obj.model, "invoke_config", None)
        prov = getattr(self.agent_obj.model, "provider", None)
        llm_client = LLMClient(user_id=str(getattr(self.agent_obj, "user_id", "") or ""), raw_cfg=raw_cfg, provider=prov)
        llm, ctx = await llm_client.init()
        self.provider_label = ctx.provider_label
        self.model_name = ctx.model_name

        # Tools
        tools_records = getattr(self.agent_obj, "tools", []) or []
        self._tools = ToolManager.load_from_records(tools_records)

        # DeepAgent
        self._deep_agent = create_deep_agent(
            model=llm,
            tools=self._tools,
            backend=FilesystemBackend(root_dir=settings.WORK_DIR, virtual_mode=True),
            context_schema=RuntimeContext,
        )

    async def astream(
        self,
        history_messages: List[Dict[str, Any]],
        *,
        context: AgentContext,
    ) -> AsyncIterator[AgentEvent]:
        if not self._deep_agent:
            await self._init()

        gathered: Optional[AIMessageChunk] = None
        emitted_text = ""
        assistant_tool_calls: Optional[List[Dict[str, Any]]] = None

        runtime_ctx = RuntimeContext(user_id=str(context.user_id or ""), db=context.db)
        async for item in self._deep_agent.astream({"messages": history_messages}, context=runtime_ctx, stream_mode=["messages"]):
            # 兼容返回结构
            if isinstance(item, (list, tuple)) and len(item) == 2:
                mode, chunk = item
            else:
                mode, chunk = "messages", item

            if mode != "messages":
                continue

            msg, metadata = chunk
            if isinstance(msg, (AIMessageChunk, AIMessage)):
                # 累积文本
                if isinstance(msg, AIMessageChunk):
                    gathered = msg if gathered is None else gathered + msg
                    final_msg = gathered
                else:
                    final_msg = msg
                    gathered = None

                content = (final_msg.content or "") if final_msg else (msg.content or "")
                if content and content.startswith(emitted_text):
                    new_text = content[len(emitted_text):]
                    if new_text:
                        emitted_text += new_text
                        yield AgentEvent("token", {"content": new_text, "final": False, "format": "markdown"})

                # 工具调用在最后一个 chunk 处理
                tool_calls = getattr(final_msg, "tool_calls", None)
                if tool_calls:
                    assistant_tool_calls = tool_calls
                    yield AgentEvent("assistant", {
                        "content": final_msg.content or "",
                        "tool_calls": tool_calls,
                    })
                    # 发送工具开始事件
                    tool_names = [tc.get("name", "") for tc in tool_calls]
                    yield AgentEvent("tool", {"tools": tool_names, "status": "started"})

            elif isinstance(msg, ToolMessage):
                tool_call_id = getattr(msg, "tool_call_id", "")
                tool_name = getattr(msg, "name", "")
                tool_content = msg.content if hasattr(msg, "content") else ""
                parsed_json = None
                content_type = "text"
                if isinstance(tool_content, str):
                    try:
                        parsed_json = json.loads(tool_content)
                        content_type = "json"
                    except Exception:
                        content_type = "text"
                yield AgentEvent("tool_msg", {
                    "content": tool_content,
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "content_type": content_type,
                    "json": parsed_json,
                    "status": "success",
                })

        # 流结束：发出 finished 工具事件（如有）与最终 assistant 文本（若无工具调用）
        if assistant_tool_calls:
            tool_names = [tc.get("name", "") for tc in assistant_tool_calls]
            yield AgentEvent("tool", {"tools": tool_names, "status": "finished"})
        if emitted_text and not assistant_tool_calls:
            yield AgentEvent("assistant", {"content": emitted_text})


def _register() -> None:
    # 延迟注册，避免循环依赖
    from app.core.agent.registry import AgentRegistry

    def factory(agent_obj: AgentModel, db: AsyncSession) -> BaseAgent:
        return DeepAgentAdapter(agent_obj, db)

    AgentRegistry.register("deepagent", factory)


_register()
