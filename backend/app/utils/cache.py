"""Redis 缓存工具类"""
import json
import logging
from typing import Optional, Any
from redis.asyncio import Redis
from redis.asyncio.connection import ConnectionPool
from app.core.config import settings

logger = logging.getLogger(__name__)

# Redis 连接池（全局单例）
_redis_pool: Optional[ConnectionPool] = None
_redis_client: Optional[Redis] = None


def get_redis_client() -> Redis:
    """获取 Redis 客户端（单例模式）"""
    global _redis_client, _redis_pool
    
    if _redis_client is None:
        _redis_pool = ConnectionPool.from_url(
            f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}",
            decode_responses=True,
            max_connections=50
        )
        _redis_client = Redis(connection_pool=_redis_pool)
        logger.info(f"✅ Redis 客户端已初始化: {settings.REDIS_HOST}:{settings.REDIS_PORT}")
    
    return _redis_client


async def close_redis_client():
    """关闭 Redis 客户端"""
    global _redis_client, _redis_pool
    
    if _redis_client:
        await _redis_client.close()
        _redis_client = None
    
    if _redis_pool:
        await _redis_pool.disconnect()
        _redis_pool = None


class AgentCache:
    """Agent 配置缓存"""
    
    CACHE_PREFIX = "agent:cache:"
    DEFAULT_TTL = 300  # 5 分钟
    
    @staticmethod
    def _get_key(agent_id: str) -> str:
        return f"{AgentCache.CACHE_PREFIX}{agent_id}"
    
    @staticmethod
    async def get(agent_id: str) -> Optional[dict]:
        """从缓存获取 Agent 配置"""
        try:
            redis_client = get_redis_client()
            key = AgentCache._get_key(agent_id)
            cached_data = await redis_client.get(key)
            
            if cached_data:
                logger.debug(f"✅ 从缓存获取 Agent: {agent_id}")
                return json.loads(cached_data)
            
            return None
        except Exception as e:
            logger.warning(f"⚠️ 从缓存获取 Agent 失败: {agent_id}, 错误: {e}")
            return None
    
    @staticmethod
    async def set(agent_id: str, agent_data: dict, ttl: int = DEFAULT_TTL) -> bool:
        """将 Agent 配置存入缓存"""
        try:
            redis_client = get_redis_client()
            key = AgentCache._get_key(agent_id)
            
            # 序列化 Agent 数据（需要处理 SQLModel 对象）
            serializable_data = _serialize_agent_data(agent_data)
            await redis_client.setex(
                key,
                ttl,
                json.dumps(serializable_data, ensure_ascii=False, default=str)
            )
            logger.debug(f"✅ Agent 已缓存: {agent_id}, TTL: {ttl}s")
            return True
        except Exception as e:
            logger.warning(f"⚠️ 缓存 Agent 失败: {agent_id}, 错误: {e}")
            return False
    
    @staticmethod
    async def delete(agent_id: str) -> bool:
        """删除 Agent 缓存"""
        try:
            redis_client = get_redis_client()
            key = AgentCache._get_key(agent_id)
            await redis_client.delete(key)
            logger.debug(f"✅ Agent 缓存已删除: {agent_id}")
            return True
        except Exception as e:
            logger.warning(f"⚠️ 删除 Agent 缓存失败: {agent_id}, 错误: {e}")
            return False


def _serialize_agent_data(agent_obj: Any) -> dict:
    """序列化 Agent 对象为可 JSON 化的字典"""
    if hasattr(agent_obj, 'model_dump'):
        # Pydantic 模型
        return agent_obj.model_dump()
    elif hasattr(agent_obj, '__dict__'):
        # SQLModel 对象
        data = {}
        for key, value in agent_obj.__dict__.items():
            if not key.startswith('_'):
                if hasattr(value, '__dict__') or hasattr(value, 'model_dump'):
                    # 嵌套对象
                    if isinstance(value, list):
                        data[key] = [_serialize_agent_data(item) for item in value]
                    else:
                        data[key] = _serialize_agent_data(value)
                else:
                    data[key] = value
        return data
    else:
        return str(agent_obj)


