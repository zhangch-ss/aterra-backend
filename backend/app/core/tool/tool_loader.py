import importlib
import pkgutil
import inspect
import sys
import threading
import time
import logging
from functools import lru_cache
from typing import Dict, List, Union, Optional, Tuple

from langchain_core.tools import BaseTool, StructuredTool


from app.models.tool import Tool

logger = logging.getLogger(__name__)


class ToolLoader:
    """工具加载器：扫描与注册统一为 BaseTool，并支持从 DB 记录映射。

    - 支持多包扫描（settings.TOOL_PACKAGES）
    - 识别 BaseTool（包含 Tool/StructuredTool）
    - DB 记录优先使用 module+function 导入，回退到 invoke_config.name 名称匹配
    - 提供加载错误与健康检查接口
    - 使用 lru_cache + 互斥锁，避免并发扫描抖动
    """

    DEFAULT_PACKAGES = ["app.core.tool.tools"]

    _lock = threading.Lock()
    _last_scan_ts: float = 0.0
    _load_errors: List[str] = []
    _origins: Dict[str, Tuple[str, str]] = {}
    # 轻量缓存：按 (module,function) 缓存已加载的 BaseTool/StructuredTool，供按需加载
    _mf_cache: Dict[Tuple[str, str], BaseTool] = {}
    # 手动覆盖扫描包列表（例如脚本在无 settings 环境下运行）
    _manual_packages: Optional[List[str]] = None

    @staticmethod
    def _get_packages() -> List[str]:
        # 先读取手动覆盖
        if ToolLoader._manual_packages and isinstance(ToolLoader._manual_packages, list) and ToolLoader._manual_packages:
            return ToolLoader._manual_packages
        try:
            # 延迟导入 settings，避免环境变量未配置导致失败
            from app.core.config import settings as _settings
            packages = getattr(_settings, "TOOL_PACKAGES", None)
            if packages and isinstance(packages, list) and packages:
                return packages
        except Exception:
            # 如果 settings 不可用或未配置，则回退默认包
            pass
        return ToolLoader.DEFAULT_PACKAGES

    @classmethod
    def set_packages(cls, packages: List[str]):
        """在无 settings 环境或脚本执行时覆盖扫描包列表。"""
        cls._manual_packages = packages
        # 更换扫描源后，需清空扫描缓存
        try:
            cls.clear_cache()
        except Exception:
            pass

    # ================= Ⅰ. 扫描所有 BaseTool =================
    @staticmethod
    @lru_cache(maxsize=1)
    def _scan_all_tools() -> Dict[str, BaseTool]:
        """扫描配置的包并返回 {tool_name: BaseTool} 映射。
        仅识别 BaseTool（包含 Tool/StructuredTool）。
        """
        with ToolLoader._lock:
            ToolLoader._load_errors.clear()
            tool_map: Dict[str, BaseTool] = {}
            packages = ToolLoader._get_packages()

            logger.info(f"🔍 正在扫描工具包: {packages}")

            for base_pkg in packages:
                try:
                    pkg = importlib.import_module(base_pkg)
                except Exception as e:
                    err = f"包导入失败: {base_pkg} - {e}"
                    ToolLoader._load_errors.append(err)
                    logger.error(err)
                    continue

                for _, mod_name, is_pkg in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + "."):
                    if is_pkg:
                        continue
                    try:
                        # 移除旧模块缓存，确保重新加载
                        if mod_name in sys.modules:
                            sys.modules.pop(mod_name)
                        mod = importlib.import_module(mod_name)
                        logger.debug(f"📦 重新导入模块: {mod_name}")

                        # 识别 BaseTool 实例（包含 Tool / StructuredTool）
                        for name, obj in inspect.getmembers(mod):
                            if isinstance(obj, BaseTool):
                                tname = getattr(obj, "name", name)
                                # 记录来源模块/函数（若为 @tool/StructuredTool 可取到 func）
                                f = getattr(obj, "func", None)
                                origin_module = getattr(f, "__module__", mod.__name__)
                                origin_function = getattr(f, "__name__", name)
                                if tname in tool_map:
                                    msg = f"工具同名冲突: {tname} 已在 {ToolLoader._origins.get(tname)}，忽略 {origin_module}.{origin_function}"
                                    ToolLoader._load_errors.append(msg)
                                    logger.warning(msg)
                                    continue
                                tool_map[tname] = obj
                                ToolLoader._origins[tname] = (origin_module, origin_function)
                                logger.info(f"✅ 发现工具: {tname} @ {origin_module}.{origin_function}")
                    except Exception as e:
                        err = f"模块导入失败: {mod_name} - {e}"
                        ToolLoader._load_errors.append(err)
                        logger.error(err)

            ToolLoader._last_scan_ts = time.time()
            logger.info(f"🧩 扫描完成，共加载 {len(tool_map)} 个工具。")
            return tool_map

    # ================= Ⅱ. 根据名称/DB 记录加载 =================
    @classmethod
    def _load_tool_by_name(cls, tool_name: str) -> Optional[BaseTool]:
        """从扫描缓存中加载指定工具对象。"""
        tool_map = cls._scan_all_tools()
        return tool_map.get(tool_name)

    @classmethod
    def load_tool_by_name(cls, tool_name: str) -> Optional[BaseTool]:
        """公开方法：按工具名称加载对象（包装私有实现）。"""
        return cls._load_tool_by_name(tool_name)

    @classmethod
    def _load_tool_by_module_func(cls, module: Optional[str], function: Optional[str]) -> Optional[BaseTool]:
        """优先按 module+function 精确导入工具，增加轻量缓存：
        - 若对象是 BaseTool/StructuredTool，加入缓存并返回
        - 其它类型不处理
        """
        if not module or not function:
            return None
        key = (module, function)
        # 命中缓存直接返回（加锁以避免并发读写竞态）
        with cls._lock:
            cached = cls._mf_cache.get(key)
        if cached:
            return cached
        try:
            mod = importlib.import_module(module)
            obj = getattr(mod, function)
            if isinstance(obj, BaseTool):
                with cls._lock:
                    cls._mf_cache[key] = obj
                return obj
            # 如果是 StructuredTool（兼容旧版）
            if isinstance(obj, StructuredTool):
                with cls._lock:
                    cls._mf_cache[key] = obj  # StructuredTool 也实现 BaseTool 接口
                return obj
            # 其它类型暂不自动适配
            logger.warning(f"对象不是 BaseTool/StructuredTool: {module}.{function}")
            return None
        except Exception as e:
            err = f"module/function 加载失败: {module}.{function} - {e}"
            ToolLoader._load_errors.append(err)
            logger.error(err)
            return None

    @classmethod
    def load_tools_from_records(cls, records: List[Union[Tool, dict]]) -> List[BaseTool]:
        """根据数据库记录加载工具，返回 BaseTool 列表。
        优先使用 module/function；否则回退到 invoke_config.name。
        """
        tools: List[BaseTool] = []
        for r in records:
            # 读取 module/function/invoke_config.name
            module = getattr(r, "module", None) if hasattr(r, "module") else r.get("module")
            function = getattr(r, "function", None) if hasattr(r, "function") else r.get("function")

            if hasattr(r, "invoke_config"):
                inv = r.invoke_config or {}
                if not isinstance(inv, dict):
                    inv = getattr(inv, "model_dump", lambda: {})()
                name = inv.get("name")
            else:
                inv = (r.get("invoke_config") or {})
                name = inv.get("name")

            tool_obj: Optional[BaseTool] = None

            # 1) module+function 优先
            tool_obj = cls._load_tool_by_module_func(module, function)

            # 2) 名称回退
            if not tool_obj and name:
                tool_obj = cls._load_tool_by_name(name)

            if tool_obj:
                tools.append(tool_obj)
            else:
                msg = f"工具加载失败: module={module}, function={function}, name={name}"
                cls._load_errors.append(msg)
                logger.error(msg)
        return tools

    # ================= Ⅲ. 缓存清理 =================
    @staticmethod
    def clear_cache():
        ToolLoader._scan_all_tools.cache_clear()
        # 同步清理按需加载缓存
        try:
            ToolLoader._mf_cache.clear()
        except Exception:
            pass
        logger.info("🧹 工具扫描缓存已清空（含 module/function 缓存）。")

    # ================= Ⅳ. 健康检查/观测 =================
    @classmethod
    def get_loaded_tools(cls) -> List[str]:
        return list(cls._scan_all_tools().keys())

    @classmethod
    def get_load_errors(cls) -> List[str]:
        # 返回最近一次扫描与加载累计的错误信息
        return list(ToolLoader._load_errors)

    @classmethod
    def get_scanned_tools_for_registry(cls) -> List[dict]:
        """提供用于注册的工具元信息列表：name/module/function/description。"""
        data: List[dict] = []
        tool_map = cls._scan_all_tools()
        for name, obj in tool_map.items():
            origin = cls._origins.get(name, (None, None))
            desc = getattr(obj, "description", None)
            data.append({
                "name": name,
                "module": origin[0],
                "function": origin[1],
                "description": desc,
            })
        return data

    @classmethod
    def get_scan_stats(cls) -> dict:
        """返回扫描观测信息：
        - loaded_count: 已加载工具数量
        - errors: 最近一次扫描的错误列表
        - last_scan_ts: 最近扫描时间戳（float 秒）
        - origins: 名称 -> (module, function)
        """
        tool_map = cls._scan_all_tools()
        return {
            "loaded_count": len(tool_map),
            "errors": list(cls._load_errors),
            "last_scan_ts": cls._last_scan_ts,
            "origins": {k: v for k, v in cls._origins.items()},
        }
