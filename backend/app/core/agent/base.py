from __future__ import annotations

import abc
from typing import Any, AsyncIterator, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession


class AgentContext:
    """运行时上下文，传递用户、DB 会话与额外参数。"""
    def __init__(
        self,
        *,
        user_id: str,
        db: AsyncSession,
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.user_id = user_id
        self.db = db
        self.extra_context = extra_context or {}


class AgentEvent:
    """统一的 Agent 事件模型（由具体 Agent 适配器产出，被 Orchestrator 消费）。

    事件类型遵循：
    - token: 增量文本 token
    - tool: 工具调用开始/结束（可按需要分 started/finished）
    - tool_msg: 工具返回的消息（包含 tool_call_id / tool_name）
    - assistant: 完整的助手消息（含 content 与可选 tool_calls）
    - final: 结束事件（包含模型信息与统计）
    """

    def __init__(self, type: str, payload: Dict[str, Any]) -> None:
        self.type = type
        self.payload = payload


class BaseAgent(abc.ABC):
    """Agent 抽象接口。所有具体 Agent 类型需实现 astream，并可选实现 run。"""

    provider_label: Optional[str] = None
    model_name: Optional[str] = None

    @abc.abstractmethod
    async def astream(
        self,
        history_messages: List[Dict[str, Any]],
        *,
        context: AgentContext,
    ) -> AsyncIterator[AgentEvent]:
        """异步事件流接口。

        history_messages: LangChain/OpenAI 兼容的消息列表（含工具消息）
        context: 运行时上下文
        """
        raise NotImplementedError

    async def run(self, task: str, *, context: AgentContext) -> str:
        """可选的非流式接口，默认抛出未实现。"""
        raise NotImplementedError("run() not implemented for this agent")

    def get_model_info(self) -> Dict[str, Any]:
        return {
            "model_id": getattr(self, "model_name", None),
            "provider": getattr(self, "provider_label", None),
        }
