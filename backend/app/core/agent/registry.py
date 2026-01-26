from __future__ import annotations

from typing import Callable, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.core.agent.base import BaseAgent


class AgentRegistry:
    """Agent 类型注册/创建工厂。"""

    _registry: Dict[str, Callable[[Agent, AsyncSession], BaseAgent]] = {}

    @classmethod
    def register(cls, kind: str, factory: Callable[[Agent, AsyncSession], BaseAgent]) -> None:
        cls._registry[kind.lower()] = factory

    @classmethod
    def create(cls, agent_obj: Agent, db: AsyncSession, *, kind: Optional[str] = None) -> BaseAgent:
        k = (kind or agent_obj.type or "deepagent").lower()
        if k not in cls._registry:
            raise ValueError(f"Unknown agent kind: {k}")
        return cls._registry[k](agent_obj, db)
