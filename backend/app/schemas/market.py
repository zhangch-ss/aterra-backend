from enum import Enum
from typing import Optional
from pydantic import BaseModel


class ResourceType(str, Enum):
    agents = "agents"
    knowledges = "knowledges"
    tools = "tools"
    prompts = "prompts"


class CopyMode(str, Enum):
    # 目前实现 shallow（仅复制当前资源本体并赋予 user_id）
    # 后续可扩展为：deep_deps（复制直接依赖）、full_tree（复制子树）
    shallow = "shallow"


class MarketAddRequest(BaseModel):
    user_id: str
    copy_mode: CopyMode = CopyMode.shallow


class MarketPublishRequest(BaseModel):
    # 预留：是否复制依赖，当前实现不复制
    copy_deps: Optional[bool] = False
