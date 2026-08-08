"""结构化日志格式与异步请求关联上下文。"""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any

_context: ContextVar[dict[str, str]] = ContextVar(
    "platform_log_context", default={}
)


def bind_log_context(**values: str | None) -> Token:
    current = dict(_context.get())
    current.update(
        {key: value for key, value in values.items() if value}
    )
    return _context.set(current)


def reset_log_context(token: Token) -> None:
    _context.reset(token)


class JsonLogFormatter(logging.Formatter):
    """输出便于Loki/ELK/OpenSearch采集的单行JSON。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            **_context.get(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(
                record.exc_info
            )
        return json.dumps(
            payload, ensure_ascii=False, default=str
        )


def configure_logging(*, level: int, json_enabled: bool) -> None:
    """幂等替换根Logger Handler，避免重复Application产生重复日志。"""
    handler = logging.StreamHandler()
    handler.setFormatter(
        JsonLogFormatter()
        if json_enabled
        else logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
