from __future__ import annotations

import inspect
import json
from typing import Any, Dict, List, Optional, get_args, get_origin

from langchain_core.tools import BaseTool
from langchain_core.tools.base import InjectedToolArg as _InjectedToolArg
from pydantic import BaseModel as _PydanticBaseModel

from app.core.tool.tool_loader import ToolLoader


class ToolManager:
    """工具加载、参数注入与敏感字段脱敏的集中管理。"""

    @staticmethod
    def load_from_records(records: List[Any]) -> List[BaseTool]:
        try:
            return ToolLoader.load_tools_from_records(records or [])
        except Exception:
            return []

    @staticmethod
    def get_secure_fields(t: BaseTool) -> set[str]:
        secure_fields: set[str] = set()
        try:
            schema = t.args_schema.schema() if hasattr(t, "args_schema") and t.args_schema else {}
            props = schema.get("properties", {})
            for fname, fdef in props.items():
                extra = fdef.get("json_schema_extra") or {}
                if extra.get("secure") is True:
                    secure_fields.add(fname)
        except Exception:
            pass
        return secure_fields

    @staticmethod
    def get_injected_params(t: BaseTool) -> dict[str, inspect.Parameter]:
        injected: dict[str, inspect.Parameter] = {}
        try:
            fn = getattr(t, "func", None) or getattr(t, "coroutine", None)
            if not fn:
                return injected
            sig = inspect.signature(fn)
            for name, p in sig.parameters.items():
                anno = p.annotation
                if get_origin(anno) is not inspect._empty and get_origin(anno) is not None:
                    # 容错：复杂 typing 场景跳过
                    pass
                if get_origin(anno) is not getattr(__import__('typing'), 'Annotated', None):
                    continue
                ann_args = get_args(anno)
                if len(ann_args) < 2:
                    continue
                marker = ann_args[-1]
                if marker is _InjectedToolArg:
                    injected[name] = p
                else:
                    try:
                        from langchain_core.tools.base import _DirectlyInjectedToolArg as _DI
                        if isinstance(marker, type) and issubclass(marker, _DI):
                            injected[name] = p
                    except Exception:
                        pass
        except Exception:
            pass
        return injected

    @staticmethod
    def build_injected_value(p: inspect.Parameter, raw_val):
        if raw_val is None:
            return None
        anno = p.annotation
        base_type = None
        from typing import Annotated, Optional, Union
        if get_origin(anno) is Annotated:
            ann_args = get_args(anno)
            real = ann_args[0]
            if get_origin(real) in (Optional, Union):
                uargs = [a for a in get_args(real) if a is not type(None)]  # noqa: E721
                base_type = uargs[0] if uargs else None
            else:
                base_type = real
        try:
            if isinstance(raw_val, dict) and isinstance(base_type, type) and issubclass(base_type, _PydanticBaseModel):
                return base_type(**raw_val)
        except Exception:
            pass
        return raw_val

    @staticmethod
    def mask_secure(data: Dict[str, Any], secs: set[str]) -> Dict[str, Any]:
        masked = dict(data or {})
        for k in secs:
            if k in masked and masked[k] is not None:
                masked[k] = "***"
        if "auth" in masked and masked["auth"] is not None:
            masked["auth"] = "***"
        return masked

    @staticmethod
    def describe_tools(tools: List[BaseTool]) -> str:
        desc_list = []
        for t in tools:
            schema = {}
            if hasattr(t, "args_schema") and t.args_schema:
                try:
                    schema = t.args_schema.schema().get("properties", {})
                except Exception:
                    schema = {}
            desc_list.append(
                f"- 工具名: {t.name}\n"
                f"  描述: {t.description or '无描述'}\n"
                f"  参数: {json.dumps(schema, ensure_ascii=False)}"
            )
        return "\n".join(desc_list) if desc_list else "（无工具可用）"
