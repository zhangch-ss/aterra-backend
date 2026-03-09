import logging
import os
import threading
import time
from typing import Optional

# Make watchdog optional: degrade gracefully if not installed
try:
    from watchdog.observers import Observer  # type: ignore
    from watchdog.events import FileSystemEventHandler  # type: ignore
except Exception:  # pragma: no cover - optional dependency path
    Observer = None  # type: ignore
    class FileSystemEventHandler:  # minimal fallback to allow import
        pass

from app.core.tool.tool_loader import ToolLoader
from app.core.tool.tool_registry import sync_scanned_tools_threadsafe

logger = logging.getLogger(__name__)


class _Debounce:
    """简单防抖器，延迟执行回调，重复触发会重置计时。"""

    def __init__(self, interval_sec: float, callback):
        self.interval = interval_sec
        self.callback = callback
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

    def trigger(self):
        with self._lock:
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(self.interval, self._run)
            self._timer.daemon = True
            self._timer.start()

    def _run(self):
        try:
            self.callback()
        finally:
            with self._lock:
                self._timer = None

    def cancel(self):
        with self._lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None


class ToolDirEventHandler(FileSystemEventHandler):
    def __init__(self, watch_dir: str, debounce: _Debounce):
        super().__init__()
        self.watch_dir = watch_dir
        self.debounce = debounce

    def _on_change(self, tag: str, path: str):
        if path.endswith(".py"):
            logger.info(f"{tag} 工具文件变更: {path}")
            # 触发一次防抖重扫
            self.debounce.trigger()

    def on_modified(self, event):
        self._on_change("🔁", event.src_path)

    def on_created(self, event):
        self._on_change("🆕", event.src_path)

    def on_deleted(self, event):
        self._on_change("🗑", event.src_path)


_observer: Optional["Observer"] = None
_debounce: Optional[_Debounce] = None


def _rescan_tools():
    """执行一次缓存清理与重扫（在防抖计时器的线程中调用）。"""
    try:
        logger.info("🔄 触发工具重扫")
        ToolLoader.clear_cache()
        ToolLoader._scan_all_tools()  # 使用缓存包装的扫描
        logger.info("✅ 工具重扫完成: %s", ToolLoader.get_loaded_tools())
        errors = ToolLoader.get_load_errors()
        if errors:
            logger.warning("⚠️ 工具加载错误: %s", errors)
        # 🗃️ 触发一次线程安全的自动注册（将扫描结果写入数据库）
        try:
            sync_scanned_tools_threadsafe()
        except Exception as e:
            logger.exception("❌ 自动注册触发失败: %s", e)
    except Exception as e:
        logger.exception("❌ 工具重扫异常: %s", e)


def start_tool_watcher():
    """后台启动目录监控（防抖 + 可停止）。"""
    global _observer, _debounce
    if Observer is None:
        logger.warning("watchdog 未安装，跳过工具目录监控。可安装 'watchdog' 并启用 settings.TOOL_WATCHER_ENABLE 后使用。")
        return
    if _observer is not None:
        logger.info("工具监控已运行，忽略重复启动。")
        return

    tool_dir = os.path.join(os.path.dirname(__file__), "tools")
    _debounce = _Debounce(interval_sec=0.5, callback=_rescan_tools)
    event_handler = ToolDirEventHandler(tool_dir, _debounce)

    observer = Observer()
    observer.schedule(event_handler, tool_dir, recursive=False)
    observer.daemon = True
    observer.start()

    _observer = observer
    logger.info(f"👀 正在监控工具目录变化: {tool_dir}")


def stop_tool_watcher():
    """停止目录监控并清理资源。应在应用关闭阶段调用。"""
    global _observer, _debounce
    try:
        if _debounce:
            _debounce.cancel()
            _debounce = None
        if _observer:
            _observer.stop()
            _observer.join(timeout=2.0)
            _observer = None
            logger.info("🛑 已停止工具目录监控。")
    except Exception as e:
        logger.exception("停止工具监控时发生异常: %s", e)
