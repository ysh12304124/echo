"""统一日志配置：输出到 compute/log 目录与控制台，风格与 backend/app/logging_setup.py 一致。

约定每条链路日志都带上 `session=<session_id>`，便于跟后台服务的日志按 session 号联合排查
一次记忆的完整处理过程（见 docs/protocols/compute-service.md「日志约定」）。
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

# compute/app/logging_setup.py -> parents[1] = compute/
LOG_DIR = Path(__file__).resolve().parents[1] / "log"
LOG_FILE = LOG_DIR / "compute.log"

_configured = False


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """初始化根日志器（幂等）。返回 compute 命名空间的日志器。"""
    global _configured
    logger = logging.getLogger("compute")
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
    """获取 compute.<name> 子日志器。"""
    return logging.getLogger(f"compute.{name}")


class _SessionLoggerAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        return f"session={self.extra.get('session_id')} {msg}", kwargs


def get_session_logger(name: str, session_id: object) -> logging.LoggerAdapter:
    """返回一个每条日志自动带 `session=<id>` 前缀的 LoggerAdapter。"""
    return _SessionLoggerAdapter(get_logger(name), {"session_id": session_id})
