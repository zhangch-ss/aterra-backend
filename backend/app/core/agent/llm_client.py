from __future__ import annotations

from typing import Any, Optional, Tuple, AsyncIterator, Dict
from langchain_openai import ChatOpenAI, AzureChatOpenAI
from pydantic import BaseModel

from app.core.model.llm_factory import build_chat_llm
from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool


class LLMContext(BaseModel):
    provider_label: Optional[str] = None
    model_name: Optional[str] = None


class LLMClient:
    """统一的 LLM 构建与调用上下文封装。"""

    def __init__(self, *, user_id: str, raw_cfg: Any, provider: Optional[str]):
        self.user_id = user_id
        self.raw_cfg = raw_cfg
        self.provider = provider
        self.llm: ChatOpenAI | AzureChatOpenAI | None = None
        self.ctx = LLMContext()

    async def init(self) -> Tuple[ChatOpenAI | AzureChatOpenAI, LLMContext]:
        llm, ctx = await build_chat_llm(
            user_id=str(self.user_id),
            cfg=self.raw_cfg,
            provider=self.provider,
        )
        self.llm = llm
        self.ctx.provider_label = ctx.provider_label
        self.ctx.model_name = ctx.model_name
        return llm, self.ctx

    async def stream_chat(
        self,
        messages: list[BaseMessage],
        *,
        tools: Optional[list[BaseTool]] = None,
        return_events: bool = True,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        统一的流式聊天接口：优先走 astream_events，其次 astream，最后回退 ainvoke+切片。

        产出标准化条目：
        - {"type": "token", "content": str}
        - 其他事件（如 astream_events 的原始事件）在此版本不直接透传，统一由 Agent 层转译。
        """
        if self.llm is None:
            raise RuntimeError("LLMClient not initialized; call init() first")

        llm = self.llm
        if tools:
            try:
                llm = llm.bind_tools(tools)
            except Exception:
                # 若绑定失败，继续使用原 llm
                pass

        # 1) 优先使用 astream_events
        if return_events and hasattr(llm, "astream_events"):
            try:
                async for ev in llm.astream_events(messages):
                    # 典型事件：on_llm_new_token / on_chat_model_start / on_chat_model_end
                    # 我们仅归一化 new_token 为 token，其他事件忽略或可后续扩展
                    try:
                        ev_type = ev.get("event")
                        data = ev.get("data", {})
                        if ev_type in ("on_llm_new_token", "on_chat_model_stream"):  # 后者为某些版本的 token 事件
                            tok = data.get("token") or data.get("chunk").content or data.get("content")
                            if tok:
                                yield {"type": "token", "content": tok}
                        elif ev_type == "on_chat_model_end":
                            # 结束事件：尝试提取最终 content 与 tool_calls
                            content = None
                            tool_calls = None
                            output = data.get("output")
                            try:
                                # ChatResult -> generations[0].message
                                if output and hasattr(output, "generations"):
                                    generations = getattr(output, "generations", [])
                                    if generations:
                                        gen0 = generations[0]
                                        msg = getattr(gen0, "message", None)
                                        content = getattr(msg, "content", None)
                                        tool_calls = getattr(msg, "tool_calls", None)
                            except Exception:
                                pass
                            # 另一种可能：data 已直接提供 message/content
                            if content is None:
                                content = data.get("content")
                            if tool_calls is None:
                                tool_calls = data.get("tool_calls")
                            yield {"type": "assistant_end", "content": content or "", "tool_calls": tool_calls}
                    except Exception:
                        # 事件格式不符合预期，忽略
                        pass
                return
            except Exception:
                # 事件流不可用，回退到 astream
                pass

        # 2) 其次使用 astream
        if hasattr(llm, "astream"):
            try:
                async for chunk in llm.astream(messages):
                    # chunk 可能是 AIMessageChunk 或 ChatGenerationChunk，尽量取 content
                    content = getattr(chunk, "content", None)
                    if content is None:
                        # 有些实现将 content 存在 .text 或 .message.content
                        content = getattr(chunk, "text", None)
                        if content is None:
                            msg = getattr(chunk, "message", None)
                            content = getattr(msg, "content", None) if msg else None
                    if content:
                        # content 可能是 list 或 str
                        if isinstance(content, list):
                            try:
                                joined = "".join([c.get("text", "") if isinstance(c, dict) else str(c) for c in content])
                                if joined:
                                    yield {"type": "token", "content": joined}
                            except Exception:
                                pass
                        elif isinstance(content, str):
                            yield {"type": "token", "content": content}
                return
            except Exception:
                # astream 不可用，回退
                pass

        # 3) 最后回退 ainvoke + 人工切片
        try:
            msg = await llm.ainvoke(messages)
            full = (getattr(msg, "content", None) or "")
        except Exception:
            full = ""
        if not full:
            return
        # 简单切片为 token（每 30 字符）
        step = 30
        for i in range(0, len(full), step):
            yield {"type": "token", "content": full[i : i + step]}
