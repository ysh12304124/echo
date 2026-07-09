"""统一日志配置：输出到 backend/log 目录与控制台。

关键链路信息（帧/语音/请求/返回）通过 `logging.getLogger("echo.*")` 记录，
既落盘到 log/echo.log（滚动切分），也打印到控制台，便于真机联调排查。
"""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

# backend/app/logging_setup.py -> parents[1] = backend/
LOG_DIR = Path(__file__).resolve().parents[1] / "log"
LOG_FILE = LOG_DIR / "echo.log"

_configured = False


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """初始化根日志器（幂等）。返回 Echo 命名空间的日志器。"""
    global _configured
    logger = logging.getLogger("echo")
    if _configured:
        return logger

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 滚动文件：单文件 10MB，保留 5 份历史。
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)

    logger.setLevel(level)
    logger.handlers.clear()
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.propagate = False

    _configured = True
    logger.info("logging initialized -> %s", LOG_FILE)
    return logger


def get_logger(name: str) -> logging.Logger:
    """获取 echo.<name> 子日志器。"""
    return logging.getLogger(f"echo.{name}")
