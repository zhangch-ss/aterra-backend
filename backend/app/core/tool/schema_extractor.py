import typing
from datetime import datetime
import json
import hashlib

# 兼容 pydantic v1/v2 的 schema 提取

def _safe_get_tool_schema(args_schema) -> dict:
    if not args_schema:
        return {}
    try:
        m = getattr(args_schema, "model_json_schema", None)
        if callable(m):
            return args_schema.model_json_schema()
        s = getattr(args_schema, "schema", None)
        if callable(s):
            return args_schema.schema()
    except Exception:
        pass
    return {}





def extract_tool_schema(tool_obj) -> tuple[dict, str | None]:
    """从工具对象提取 LLM 入参 schema 以及推断的版本。
    总是返回 (schema: dict, version: Optional[str]) 元组。
    版本为 schema 的稳定哈希；若无 schema 则为 None。
    """
    try:
        args_schema = getattr(tool_obj, "args_schema", None)
        schema = _safe_get_tool_schema(args_schema)
        version: str | None = None
        if schema:
            payload = json.dumps(schema, ensure_ascii=False, sort_keys=True)
            version = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return schema or {}, version
    except Exception:
        return {}, None


def unwrap_type(t):
    origin = typing.get_origin(t)
    if origin is typing.Union:
        args = [a for a in typing.get_args(t) if a is not type(None)]
        return args[0] if args else None
    return t

def extract_runtime_parameters(tool_obj) -> dict:
    """解析工具函数签名，提取第一个 InjectedToolArg 的 BaseModel schema。"""
    import inspect
    from pydantic import BaseModel
    from langchain_core.tools import InjectedToolArg

    func = getattr(tool_obj, "func", tool_obj)
    sig = inspect.signature(func)

    for p in sig.parameters.values():
        ann = p.annotation
        origin = typing.get_origin(ann)
        if origin is typing.Annotated:
            args = typing.get_args(ann)
            if not args:
                continue
            # ✅ 解包 Optional/Union
            param_type = unwrap_type(args[0])

            # 检查 InjectedToolArg 标记
            metas = args[1:]
            if not any(m is InjectedToolArg or getattr(m, "__name__", "") == "InjectedToolArg" for m in metas):
                continue

            # ✅ 找到 BaseModel 类
            if isinstance(param_type, type) and issubclass(param_type, BaseModel):
                # Pydantic v2
                if hasattr(param_type, "model_json_schema"):
                    return param_type.model_json_schema()
                # v1 fallback
                elif hasattr(param_type, "schema"):
                    return param_type.schema()
    return {}



def compute_schema_hash(tool_schema: dict | None, runtime_parameters: dict | None) -> str:
    """对 schema 做稳定序列化并计算哈希，用于变更检测。"""
    payload = {
        "tool_schema": tool_schema or {},
        "runtime_parameters": runtime_parameters or {},
    }
    # 使用 sort_keys 保证稳定
    s = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def now_ts() -> datetime:
    return datetime.utcnow()
