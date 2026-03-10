from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.chat_crud import crud_chat
from app.utils import ephemeral_store as eph


class ChatHistoryStore:
    """历史消息存储抽象：支持数据库与临时会话两种模式。"""

    def __init__(self, *, db: AsyncSession, persist: bool) -> None:
        self.db = db
        self.persist = persist

    async def get_messages_by_session(self, session_id: str) -> List[Dict[str, Any]]:
        if self.persist:
            history_msgs = await crud_chat.get_messages_by_session(session_id=session_id, db_session=self.db)
            return [self._db_msg_to_dict(m) for m in history_msgs]
        else:
            eph_msgs = await eph.get_messages(session_id)
            return eph_msgs

    def _db_msg_to_dict(self, msg) -> Dict[str, Any]:
        d: Dict[str, Any] = {"role": msg.role, "content": msg.content}
        if msg.role == "assistant" and msg.tool_calls:
            d["tool_calls"] = msg.tool_calls
        if msg.role == "tool":
            d["tool_call_id"] = msg.tool_call_id or ""
            if msg.tool_name:
                d["tool_name"] = msg.tool_name
        return d

    @staticmethod
    def to_langchain_messages(
        raw_msgs: List[Dict[str, Any]],
        *,
        include_user_input: bool = False,
        user_input: str = "",
    ) -> List[Dict[str, Any]]:
        """将原始历史消息转换为 LangChain/AOAI 兼容格式。"""
        context: List[Dict[str, Any]] = []
        for msg in raw_msgs:
            role = msg.get("role")
            if role == "user":
                context.append({"role": "user", "content": msg.get("content", "")})
            elif role == "assistant":
                entry: Dict[str, Any] = {"role": "assistant", "content": msg.get("content", "")}
                tc_wrapper = msg.get("tool_calls") or {}
                tool_calls_list = tc_wrapper.get("tool_calls", [])
                if tool_calls_list:
                    entry["tool_calls"] = []
                    for tc in tool_calls_list:
                        args_str = tc.get("arguments", "{}")
                        try:
                            args = json.loads(args_str) if isinstance(args_str, str) else (args_str or {})
                        except (json.JSONDecodeError, TypeError):
                            args = {}
                        entry["tool_calls"].append({
                            "id": tc.get("id", ""),
                            "name": tc.get("name", ""),
                            "args": args,
                        })
                context.append(entry)
            elif role == "tool":
                entry = {
                    "role": "tool",
                    "content": msg.get("content", ""),
                    "tool_call_id": msg.get("tool_call_id", ""),
                }
                if msg.get("tool_name"):
                    entry["name"] = msg.get("tool_name")
                context.append(entry)
        if include_user_input and user_input:
            context.append({"role": "user", "content": user_input})
        return context

    @staticmethod
    def serialize_tool_calls(tool_calls: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        tool_calls_data: List[Dict[str, str]] = []
        for tc in tool_calls:
            tool_call_id = tc.get("id", "")
            tool_name = tc.get("name", "")
            args = tc.get("args", "") or tc.get("arguments", "")
            if isinstance(args, str):
                try:
                    args_dict = json.loads(args)
                    arguments_str = json.dumps(args_dict, ensure_ascii=False)
                except (json.JSONDecodeError, TypeError):
                    arguments_str = args or "{}"
            elif isinstance(args, dict):
                arguments_str = json.dumps(args, ensure_ascii=False)
            else:
                arguments_str = "{}"
            tool_calls_data.append({
                "id": tool_call_id,
                "name": tool_name,
                "arguments": arguments_str,
            })
        return tool_calls_data
