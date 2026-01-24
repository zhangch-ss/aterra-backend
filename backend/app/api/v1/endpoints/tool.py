from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, update as sa_update
from app.api.deps import get_db
from app.crud.tool_crud import crud_tool
from app.schemas.tool import ToolTypeOut, ToolCreate, CreateToolCardOut, ToolDetailOut
from app.core.tool.tool_loader import ToolLoader
from app.models.link import AgentToolLink
from app.models.tool import Tool

router = APIRouter()


# ✅ 获取工具类型列表
@router.get("/tool_type", response_model=list[ToolTypeOut])
async def get_tool_types(db: AsyncSession = Depends(get_db)):
    return await crud_tool.get_tool_type(db_session=db)

# ✅ 工具加载健康检查
@router.get("/loaded", response_model=list[str])
async def get_loaded_tools():
    return ToolLoader.get_loaded_tools()

@router.get("/errors", response_model=list[str])
async def get_tool_errors():
    return ToolLoader.get_load_errors()

# ✅ 获取工具参数 Schema（包含 source/secure 元数据）
@router.get("/schema/name/{tool_name}")
async def get_tool_schema(tool_name: str):
    obj = ToolLoader._load_tool_by_name(tool_name)
    if not obj:
        raise HTTPException(status_code=404, detail="工具未找到")
    schema = {}
    if hasattr(obj, "args_schema") and getattr(obj, "args_schema"):
        try:
            schema = obj.args_schema.schema()
        except Exception:
            schema = {}
    return {
        "name": getattr(obj, "name", tool_name),
        "description": getattr(obj, "description", None),
        "schema": schema,
    }

# ✅ 手动触发一次扫描并注册到数据库（按 module+function 唯一）
@router.post("/sync", response_model=list[CreateToolCardOut])
async def sync_scanned_tools(db: AsyncSession = Depends(get_db)):
    scanned = ToolLoader.get_scanned_tools_for_registry()
    updated = await crud_tool.upsert_scanned_tools(scanned=scanned, db_session=db)
    return updated


# ✅ 创建工具卡片
@router.post("/create", response_model=CreateToolCardOut)
async def create_tool(payload: ToolCreate, db: AsyncSession = Depends(get_db)):

    data = await crud_tool.create(obj_in=payload, db_session=db)
    return data

# ✅ 查询工具列表
@router.get("/list_tools", response_model=list[CreateToolCardOut])
async def list_tools(
    user_id: str, 
    type: str | None = None,
    scene: str | None = None,
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db)
    ):

    tools = await crud_tool.get_by_user_id(user_id=user_id, type=type, scene=scene, keyword=keyword, db_session=db)
    return tools

# ✅ 获取单个工具详情
@router.get("/{tool_id}", response_model=ToolDetailOut)
async def get_tool(tool_id: str, db: AsyncSession = Depends(get_db)):
    tool = await crud_tool.get(id=tool_id, db_session=db)
    if not tool:
        raise HTTPException(status_code=404, detail="工具不存在")

    # 直接返回原始运行时参数（包含明文），不做遮罩
    return tool

from typing import Any, Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict
from app.utils.credentials_store import store_provider_credentials, delete_provider_credentials

MASK_SENTINEL = "***masked***"
SECURE_KEY_HINTS = {"api_key", "apikey", "token", "access_token", "refresh_token", "secret", "client_secret", "password", "pwd", "access_key"}

class RuntimeConfigUpdate(BaseModel):
    values: Optional[dict[str, Any]] = None
    # 可选：清除指定密钥键
    clear_secret_keys: Optional[list[str]] = None
    # 可选：Provider 标识（用于将密钥落到 ProviderCredentials）
    provider: Optional[str] = None
    model_config = ConfigDict(extra="ignore")


def _is_secure_key_name(key: str) -> bool:
    k = key.lower().replace("-", "_")
    return k in SECURE_KEY_HINTS


def _collect_secure_keys(schema: dict | None, values: dict[str, Any] | None) -> set[str]:
    secure: set[str] = set()
    props = (schema or {}).get("properties", {}) if isinstance(schema, dict) else {}
    for k, meta in props.items():
        if isinstance(meta, dict) and bool(meta.get("secure")):
            secure.add(k)
    for k in (values or {}).keys():
        if _is_secure_key_name(k):
            secure.add(k)
    return secure


@router.put("/{tool_id}/runtime-config")
async def update_runtime_config(tool_id: str, payload: RuntimeConfigUpdate, db: AsyncSession = Depends(get_db)):
    tool = await crud_tool.get(id=tool_id, db_session=db)
    if not tool:
        raise HTTPException(status_code=404, detail="工具不存在")

    rp: dict = getattr(tool, "runtime_parameters", None) or {}
    schema: dict | None = rp.get("schema") if isinstance(rp, dict) else None
    current_values: dict[str, Any] = (rp.get("values") or {}) if isinstance(rp, dict) else {}
    incoming_values: dict[str, Any] = payload.values or {}

    # 收集密钥键
    secure_keys = _collect_secure_keys(schema, current_values | incoming_values)

    # 处理清除请求（如有 provider 则清除其密钥）
    if payload.clear_secret_keys:
        for key in payload.clear_secret_keys:
            if key in secure_keys:
                # 清除 Provider 级密钥（仅处理常见 api_key）
                if payload.provider and _is_secure_key_name(key):
                    try:
                        await delete_provider_credentials(redis=None, user_id=tool.user_id or "", provider=payload.provider)
                    except Exception:
                        pass
                # 标记为未设置
                current_values[key] = None
                # 可选：记录到 secrets 元信息
                secrets_meta = rp.get("secrets", {})
                if isinstance(secrets_meta, dict):
                    secrets_meta[key] = {"secure": True, "has_secret": False, "last_updated_at": datetime.utcnow().isoformat()}
                    rp["secrets"] = secrets_meta

    # 合并非敏感值；密钥值按占位与专库存储处理
    for k, v in incoming_values.items():
        if k in secure_keys:
            # 未改动或占位符则忽略（兼容旧客户端可能仍上传占位符）
            if v is None or (isinstance(v, str) and v.strip() == MASK_SENTINEL):
                continue
            # 明文直接落到 runtime_parameters.values
            current_values[k] = v
            # 如提供了 provider，仍可同步更新 ProviderCredentials（可选，保留兼容）
            if payload.provider and _is_secure_key_name(k):
                try:
                    await store_provider_credentials(
                        redis=None,
                        user_id=tool.user_id or "",
                        provider=payload.provider,
                        api_key=str(v) if v is not None else None,
                    )
                except Exception:
                    # 不抛出敏感错误，避免泄露
                    pass
            # 更新 secrets 元信息（标注存在明文值）
            secrets_meta = rp.get("secrets", {})
            if isinstance(secrets_meta, dict):
                secrets_meta[k] = {"secure": True, "has_secret": True, "stored_plaintext": True, "last_updated_at": datetime.utcnow().isoformat()}
                rp["secrets"] = secrets_meta
        else:
            # 普通键合并更新
            current_values[k] = v


    rp["values"] = current_values

    # 提交更新（统一使用同一会话），刷新更新时间
    tool = await crud_tool.update(
        obj_current=tool,
        obj_new={"runtime_parameters": rp, "updated_at": datetime.utcnow()},
        db_session=db,
    )

    # 返回非敏感值与占位后的密钥显示状态
    return {
        "ok": True,
        "tool_id": tool_id,
        "values": rp.get("values", {}),
        "secrets": rp.get("secrets", {}),
    }


# ✅ 删除工具（先清理 Agent ↔ Tool 关联，避免外键约束失败）
@router.delete("/{tool_id}")
async def delete_tool(tool_id: str, db: AsyncSession = Depends(get_db)):
    tool = await crud_tool.get(id=tool_id, db_session=db)
    if not tool:
        raise HTTPException(status_code=404, detail="工具不存在")

    # 先删除关联关系（agenttoollink），再删除工具
    await db.execute(delete(AgentToolLink).where(AgentToolLink.tool_id == tool_id))
    await db.commit()

    await crud_tool.remove(id=tool_id, db_session=db)
    return {"ok": True, "tool_id": tool_id}
