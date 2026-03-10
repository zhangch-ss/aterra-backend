from __future__ import annotations

import inspect
import json
from typing import Any, Dict, List, Optional, get_args, get_origin

from langchain_core.tools import BaseTool
from langchain_core.tools.base import InjectedToolArg as _InjectedToolArg
from pydantic import BaseModel as _PydanticBaseModel

from app.core.tool.tool_loader import ToolLoader
from app.core.tool.schema_extractor import extract_tool_schema


class ToolManager:
    """工具加载、参数注入与敏感字段脱敏的集中管理。

    统一提供：
    - load_from_records(records, include_defaults=True): 支持在记录为空时回退加载默认工具
    - prepare_args(tool_obj, args, extra_context): 统一处理运行时参数注入与敏感字段脱敏
    """

    @staticmethod
    def load_from_records(records: List[Any], include_defaults: bool = True) -> List[BaseTool]:
        """从数据库记录加载工具；当记录为空且允许时，回退到默认已加载工具。

        include_defaults 为 True 时：
        - 若 records 为空，尝试通过 ToolLoader.get_loaded_tools()/._load_tool_by_name 加载默认工具。
        """
        try:
            tools = ToolLoader.load_tools_from_records(records or [])
        except Exception:
            tools = []

        if include_defaults and not tools:
            try:
                loaded_names = ToolLoader.get_loaded_tools()
                for name in loaded_names:
                    obj = ToolLoader.load_tool_by_name(name)
                    if obj:
                        tools.append(obj)
            except Exception:
                # 默认工具加载异常时，返回已有列表
                pass
        return tools

    @staticmethod
    def get_secure_fields(t: BaseTool) -> set[str]:
        secure_fields: set[str] = set()
        try:
            schema, _ = extract_tool_schema(t)
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
            schema, _ = extract_tool_schema(t)
            try:
                props = schema.get("properties", {})
            except Exception:
                props = {}
            desc_list.append(
                f"- 工具名: {t.name}\n"
                f"  描述: {t.description or '无描述'}\n"
                f"  参数: {json.dumps(props, ensure_ascii=False)}"
            )
        return "\n".join(desc_list) if desc_list else "（无工具可用）"

    @staticmethod
    def prepare_args(tool_obj: BaseTool, args: Dict[str, Any] | None, extra_context: Optional[Dict[str, Any]] = None) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """统一构建工具调用参数：

        - 合并 LLM 给出的 args 与运行时注入参数（runtime_params/form_params）
        - 依据 Injected 标记将上下文值转为目标类型（支持 pydantic BaseModel）
        - 产出脱敏后的 masked_args（secure 字段与 auth 字段隐藏）

        返回：real_args, masked_args
        """
        secure_fields = ToolManager.get_secure_fields(tool_obj)
        injected_params = ToolManager.get_injected_params(tool_obj)

        extra = extra_context or {}
        # 兼容旧字段：优先 runtime_params，其次 form_params
        runtime_params_all = extra.get("runtime_params") or extra.get("form_params") or {}

        tool_name = getattr(tool_obj, "name", None)
        runtime_params_for_tool = {}
        if isinstance(runtime_params_all, dict) and tool_name:
            runtime_params_for_tool = runtime_params_all.get(tool_name, {}) or {}

        real_args: Dict[str, Any] = dict(args or {})

        # 注入参数：
        for name, p in injected_params.items():
            raw_val = None
            if isinstance(runtime_params_for_tool, dict) and name in runtime_params_for_tool:
                raw_val = runtime_params_for_tool[name]
            elif name in extra:
                raw_val = extra[name]
            val = ToolManager.build_injected_value(p, raw_val)
            if val is not None:
                real_args[name] = val

        masked_args = ToolManager.mask_secure(real_args, secure_fields)
        return real_args, masked_args
