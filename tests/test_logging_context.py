"""结构化日志与关联上下文测试。"""

import json
import logging

from app.core.logging_context import (
    JsonLogFormatter,
    bind_log_context,
    reset_log_context,
)


def test_json_log_contains_bound_request_id() -> None:
    token = bind_log_context(request_id="request-123")
    try:
        record = logging.LogRecord(
            "test.logger",
            logging.INFO,
            __file__,
            1,
            "hello %s",
            ("world",),
            None,
        )
        payload = json.loads(JsonLogFormatter().format(record))
    finally:
        reset_log_context(token)

    assert payload["message"] == "hello world"
    assert payload["request_id"] == "request-123"
    assert payload["level"] == "INFO"
