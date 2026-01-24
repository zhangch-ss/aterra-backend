import logging
import json
from datetime import datetime
from typing import Optional
from colorlog import ColoredFormatter


LOG_COLORS = {
    "DEBUG":    "thin_white",
    "INFO":     "white",
    "WARNING":  "yellow",
    "ERROR":    "red",
    "CRITICAL": "bold_red",
}


STATE_COLORS = {
    "PLAN":    "\033[94m",   # 蓝
    "ACT":     "\033[92m",   # 绿
    "REFLECT": "\033[95m",   # 紫
    "VERIFY":  "\033[96m",   # 青
    "RESPOND": "\033[92m",   # 亮绿
    "REPLAN":  "\033[93m",   # 黄
    "RESET":   "\033[0m",
}


class StateHighlightFilter(logging.Filter):
    """
    对 [STATE]、[PLAN]、[ACT] 等关键词高亮
    """
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()

        for key, color in STATE_COLORS.items():
            if key != "RESET" and f"[{key}]" in msg:
                record.msg = (
                    msg.replace(
                        f"[{key}]",
                        f"{color}[{key}]{STATE_COLORS['RESET']}"
                    )
                )
                break
        return True


def setup_logger(
    name: str,
    level: int = logging.INFO,
    log_file: Optional[str] = None,
) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False

    if logger.handlers:
        return logger

    # ========= Console Handler (彩色) =========
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)

    console_formatter = ColoredFormatter(
        fmt=(
            "%(log_color)s"
            "[%(asctime)s] "
            "[%(levelname)-8s] "
            "%(name)s - %(message)s"
        ),
        datefmt="%H:%M:%S",
        log_colors=LOG_COLORS,
    )

    console_handler.setFormatter(console_formatter)
    console_handler.addFilter(StateHighlightFilter())
    logger.addHandler(console_handler)

    # ========= File Handler (无色，结构化) =========
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)

        file_formatter = logging.Formatter(
            fmt="[%(asctime)s] [%(levelname)s] %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

    return logger


def pretty(obj, max_len=800):
    """
    JSON / dict / str 的安全打印
    """
    try:
        text = json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        text = str(obj)

    if len(text) > max_len:
        return text[:max_len] + " ... (truncated)"
    return text
