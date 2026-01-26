from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.tools import BaseTool

from app.core.agent.base import AgentEvent


class AgentEmit:
    """统一的 AgentEvent 构造辅助类，避免各 Agent 重复拼装 payload。"""

    @staticmethod
    def token(content: str, *, final: bool = False, format: str = "markdown") -> AgentEvent:
        return AgentEvent("token", {"content": content, "final": final, "format": format})

    @staticmethod
    def assistant(content: str, *, tool_calls: Optional[List[Dict[str, Any]]] = None) -> AgentEvent:
        payload: Dict[str, Any] = {"content": content}
        if tool_calls is not None:
            payload["tool_calls"] = tool_calls
        return AgentEvent("assistant", payload)

    @staticmethod
    def tool_started(tools: List[Dict[str, Any]]) -> AgentEvent:
        return AgentEvent("tool", {"tools": tools, "status": "started"})

    @staticmethod
    def tool_finished(tools: List[Dict[str, Any]]) -> AgentEvent:
        return AgentEvent("tool", {"tools": tools, "status": "finished"})

    @staticmethod
    def tool_msg(
        content: str,
        *,
        tool_call_id: str,
        tool_name: str,
        content_type: str = "text",
        json: Optional[Dict[str, Any]] = None,
        status: str = "success",
    ) -> AgentEvent:
        payload: Dict[str, Any] = {
            "content": content,
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "content_type": content_type,
            "status": status,
        }
        if json is not None:
            payload["json"] = json
        return AgentEvent("tool_msg", payload)

    @staticmethod
    def error(content: str, *, code: int = 500) -> AgentEvent:
        return AgentEvent("error", {"content": content, "code": code})


async def run_tool_with_events(
    tool_obj: BaseTool,
    *,
    real_args: Dict[str, Any],
    masked_args: Dict[str, Any],
) -> Tuple[List[AgentEvent], Any]:
    """
    执行工具并生成标准事件序列：started -> tool_msg -> finished。

    返回：(events, tool_result)
    """
    events: List[AgentEvent] = []
    tool_name = getattr(tool_obj, "name", "unknown_tool")
    tools_payload = [{"name": tool_name, "args_masked": masked_args}]
    events.append(AgentEmit.tool_started(tools_payload))

    tool_call_id = f"tool_{uuid.uuid4().hex[:12]}"
    try:
        tool_res = await tool_obj.ainvoke(real_args)
        content = str(tool_res)
        events.append(
            AgentEmit.tool_msg(
                content=content,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                content_type="text",
                json=None,
                status="success",
            )
        )
    except Exception as e:
        content = f"TOOL_ERROR: {str(e)}"
        tool_res = content
        events.append(
            AgentEmit.tool_msg(
                content=content,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                content_type="text",
                json=None,
                status="error",
            )
        )

    events.append(AgentEmit.tool_finished([{"name": tool_name}]))
    return events, tool_res


async def stream_llm_phase(
    llm_client,
    messages: List[Any],
    *,
    tools: Optional[List[BaseTool]] = None,
    out: Optional[Dict[str, Any]] = None,
) -> Any:
    """
    通用的 LLM 流式阶段封装：
    - 通过 LLMClient.stream_chat 统一消费底层 astream_events/astream 回退逻辑
    - 即时向上层产出 AgentEmit.token 事件
    - 结束时在 out 中写入 {'content': final_text, 'tool_calls': captured_tool_calls}

    用法示例：
        result = {}
        async for e in stream_llm_phase(llm_client, messages, tools=tool_list, out=result):
            yield e
        final_text = result.get('content', '')
        tool_calls = result.get('tool_calls')
    """
    buf: List[str] = []
    captured_tool_calls = None
    async for ev in llm_client.stream_chat(messages, tools=tools or None, return_events=True):
        et = ev.get("type")
        if et == "token":
            tok = ev.get("content", "")
            if tok:
                buf.append(tok)
                yield AgentEmit.token(tok)
        elif et == "assistant_end":
            captured_tool_calls = ev.get("tool_calls")
            content = ev.get("content") or ""
            if content:
                buf.append(content)

    if out is not None:
        out["content"] = "".join(buf)
        out["tool_calls"] = captured_tool_calls
