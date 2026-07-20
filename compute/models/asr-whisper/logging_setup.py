"""统一日志配置：输出到 asr-whisper/log/asr.log 与控制台。

风格与 backend/app/logging_setup.py、compute/app/logging_setup.py 一致，只用一份
滚动文件日志，不额外产生 uvicorn.log/uvicorn.out。
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent / "log"
LOG_FILE = LOG_DIR / "asr.log"

_configured = False


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """初始化根日志器（幂等）。返回 asr 命名空间的日志器。"""
    global _configured
    logger = logging.getLogger("asr")
    if _configured:
        return logger

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

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
    """获取 asr.<name> 子日志器。"""
    return logging.getLogger(f"asr.{name}")
