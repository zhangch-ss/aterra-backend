from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent.base import AgentContext, BaseAgent, AgentEvent
from app.core.agent.history import ChatHistoryStore
from app.crud.chat_crud import crud_chat
from app.schemas.chat import MessageCreate
from app.utils import ephemeral_store as eph


class AgentOrchestrator:
    """统一的 SSE 编排层：
    - 构建历史上下文
    - 消费 BaseAgent 事件流，转换为 SSE payload
    - 批量持久化消息（DB 或临时会话）
    """

    def __init__(self, *, db: AsyncSession):
        self.db = db

    async def stream_response(
        self,
        agent: BaseAgent,
        *,
        user_id: str,
        session_id: str,
        user_input: str,
        persist_history: bool = True,
        ephemeral_ttl_seconds: Optional[int] = None,
        ephemeral_cleanup: bool = False,
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> StreamingResponse:
        message_id = f"msg_{uuid.uuid4().hex[:12]}"
        trace_id = f"trace_{uuid.uuid4().hex[:12]}"
        protocol_version = "v1"
        start_time = datetime.utcnow()

        store = ChatHistoryStore(db=self.db, persist=persist_history)
        raw_msgs = await store.get_messages_by_session(session_id)
        history = ChatHistoryStore.to_langchain_messages(raw_msgs, include_user_input=True, user_input=user_input)

        # 先保存用户输入
        if persist_history:
            await crud_chat.create_message(
                session_id=session_id,
                msg_in=MessageCreate(role="user", content=user_input),
                db_session=self.db,
            )
        else:
            await eph.append_message(session_id, {"role": "user", "content": user_input}, ttl_seconds=ephemeral_ttl_seconds)

        async def generate():
            messages_to_save: List[Dict[str, Any]] = []
            assistant_tool_calls = None
            ai_chunks: List[str] = []
            chunk_index = 0
            final_sent = False
            assistant_msg_emitted = False

            try:
                ctx = AgentContext(user_id=user_id, db=self.db, extra_context=extra_context)
                async for evt in agent.astream(history_messages=history, context=ctx):
                    if evt.type == "token":
                        content = evt.payload.get("content", "")
                        if content:
                            ai_chunks.append(content)
                            payload = {
                                'type': 'token',
                                'content': content,
                                'final': False,
                                'format': evt.payload.get('format', 'markdown'),
                                'index': chunk_index,
                                'session_id': session_id,
                                'message_id': message_id,
                                'protocol_version': protocol_version,
                                'created_at': datetime.utcnow().isoformat() + 'Z',
                                'trace_id': trace_id,
                            }
                            yield f"data: {json.dumps(payload)}\n\n"
                            chunk_index += 1

                    elif evt.type == "assistant":
                        content = evt.payload.get("content") or ""
                        tool_calls = evt.payload.get("tool_calls")
                        if tool_calls:
                            assistant_tool_calls = tool_calls
                            tool_calls_data = ChatHistoryStore.serialize_tool_calls(tool_calls)
                            messages_to_save.append({
                                "role": "assistant",
                                "content": content,
                                "tool_calls": {"tool_calls": tool_calls_data},
                            })
                        else:
                            # 纯文本回复
                            if content:
                                messages_to_save.append({"role": "assistant", "content": content})
                        assistant_msg_emitted = True

                    elif evt.type == "tool":
                        payload = {
                            'type': 'tool',
                            'tools': evt.payload.get('tools', []),
                            'status': evt.payload.get('status', 'started'),
                            'session_id': session_id,
                            'message_id': message_id,
                            'protocol_version': protocol_version,
                            'created_at': datetime.utcnow().isoformat() + 'Z',
                            'trace_id': trace_id,
                        }
                        yield f"data: {json.dumps(payload)}\n\n"

                    elif evt.type == "tool_msg":
                        content = evt.payload.get("content", "")
                        tool_call_id = evt.payload.get("tool_call_id", "")
                        tool_name = evt.payload.get("tool_name", "")
                        content_type = evt.payload.get("content_type", "text")
                        parsed_json = evt.payload.get("json")
                        messages_to_save.append({
                            "role": "tool",
                            "content": content,
                            "tool_call_id": tool_call_id,
                            "tool_name": tool_name,
                        })
                        payload = {
                            'type': 'tool_msg',
                            'content': content,
                            'tool_call_id': tool_call_id,
                            'tool_name': tool_name,
                            'content_type': content_type,
                            'json': parsed_json,
                            'status': evt.payload.get('status', 'success'),
                            'session_id': session_id,
                            'message_id': message_id,
                            'protocol_version': protocol_version,
                            'created_at': datetime.utcnow().isoformat() + 'Z',
                            'trace_id': trace_id,
                        }
                        yield f"data: {json.dumps(payload)}\n\n"

                # 流结束后的持久化与最终事件
                ai_text = "".join(ai_chunks).strip()
                if ai_text and assistant_tool_calls:
                    # 更新最后一条 assistant（带 tool_calls）的 content
                    for i in range(len(messages_to_save) - 1, -1, -1):
                        m = messages_to_save[i]
                        if m.get("role") == "assistant" and m.get("tool_calls"):
                            m["content"] = ai_text
                            break
                elif ai_text and not assistant_tool_calls and not assistant_msg_emitted:
                    # 若没有工具调用且之前未显式发送 assistant 事件，仅文本回复
                    messages_to_save.append({"role": "assistant", "content": ai_text})

                if messages_to_save:
                    if persist_history:
                        try:
                            saved_messages = await crud_chat.bulk_create_messages(
                                session_id=session_id,
                                messages_data=messages_to_save,
                                db_session=self.db,
                            )
                        except Exception:
                            pass
                    else:
                        try:
                            await eph.bulk_append_messages(session_id, messages_to_save, ttl_seconds=ephemeral_ttl_seconds)
                        except Exception:
                            pass
                        finally:
                            if ephemeral_cleanup:
                                try:
                                    await eph.clear_session(session_id)
                                except Exception:
                                    pass

                if not final_sent:
                    elapsed_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
                    final_payload = {
                        'type': 'token',
                        'content': '',
                        'final': True,
                        'finish_reason': 'stop',
                        'format': 'markdown',
                        'index': chunk_index,
                        'session_id': session_id,
                        'message_id': message_id,
                        'protocol_version': protocol_version,
                        'created_at': datetime.utcnow().isoformat() + 'Z',
                        'trace_id': trace_id,
                        'model_info': {
                            'model_id': getattr(agent, 'model_name', None),
                            'provider': getattr(agent, 'provider_label', None),
                            'latency_ms': elapsed_ms,
                        },
                    }
                    yield f"data: {json.dumps(final_payload)}\n\n"
                    final_sent = True

            except Exception as e:
                err = f"[Agent Error]: {str(e)}"
                payload = {
                    'type': 'error',
                    'content': err,
                    'code': 500,
                    'session_id': session_id,
                    'message_id': message_id,
                    'protocol_version': protocol_version,
                    'created_at': datetime.utcnow().isoformat() + 'Z',
                    'trace_id': trace_id,
                }
                yield f"data: {json.dumps(payload)}\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")
