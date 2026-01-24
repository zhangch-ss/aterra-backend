# app/utils/ephemeral_store.py
import json
from typing import Any, Dict, List, Optional
from datetime import timedelta
from redis.asyncio import Redis

from app.core.config import settings

# Key namespaces
EPHEMERAL_MSG_LIST = "chat:ephemeral:{session_id}:messages"  # Redis list of JSON strings


def get_redis_client() -> Redis:
    return Redis(host=settings.REDIS_HOST, port=int(settings.REDIS_PORT), decode_responses=True)


async def append_message(session_id: str, message: Dict[str, Any], ttl_seconds: Optional[int] = None) -> None:
    """Append a message to the ephemeral list. Optionally refresh TTL.
    Message should be a JSON-serializable dict, e.g. {role, content, tool_calls|tool_call_id|tool_name}.
    """
    key = EPHEMERAL_MSG_LIST.format(session_id=session_id)
    data = json.dumps(message, ensure_ascii=False)
    client = get_redis_client()
    await client.rpush(key, data)
    if ttl_seconds:
        await client.expire(key, ttl_seconds)


async def bulk_append_messages(session_id: str, messages: List[Dict[str, Any]], ttl_seconds: Optional[int] = None) -> None:
    key = EPHEMERAL_MSG_LIST.format(session_id=session_id)
    client = get_redis_client()
    if messages:
        async with client.pipeline(transaction=True) as pipe:
            for m in messages:
                await pipe.rpush(key, json.dumps(m, ensure_ascii=False))
            if ttl_seconds:
                await pipe.expire(key, ttl_seconds)
            await pipe.execute()


async def get_messages(session_id: str) -> List[Dict[str, Any]]:
    key = EPHEMERAL_MSG_LIST.format(session_id=session_id)
    client = get_redis_client()
    raw_list = await client.lrange(key, 0, -1)
    msgs: List[Dict[str, Any]] = []
    for s in raw_list or []:
        try:
            msgs.append(json.loads(s))
        except Exception:
            # skip bad entries
            continue
    return msgs


async def clear_session(session_id: str) -> None:
    key = EPHEMERAL_MSG_LIST.format(session_id=session_id)
    client = get_redis_client()
    await client.delete(key)


async def set_ttl(session_id: str, ttl_seconds: int) -> None:
    key = EPHEMERAL_MSG_LIST.format(session_id=session_id)
    client = get_redis_client()
    await client.expire(key, ttl_seconds)
