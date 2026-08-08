"""
Runtime运行上下文
管理一次请求生命周期。
"""

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.runtime.request import RuntimeRequest


class RuntimeStatus(str, Enum):
    """
    Runtime请求生命周期状态。
    """

    CREATED = "created"
    PREPARING = "preparing"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"

@dataclass
class RuntimeContext:
    """
    Runtime上下文
    """

    # 请求对象
    request: RuntimeRequest

    # Trace ID
    trace_id: str = field(
        default_factory=lambda: str(uuid.uuid4())
    )

    # 当前Agent名称
    agent_name: str = ""

    # 当前状态
    status: RuntimeStatus = RuntimeStatus.CREATED

    # 开始时间
    start_time: float = field(
        default_factory=time.time
    )
    # 执行数据
    state: dict[str, Any] = field(
        default_factory=dict
    )
    # 错误信息
    error: Exception | None = None
    # 最终响应
    response: Any = None

    def __post_init__(self) -> None:
        if not self.agent_name:
            self.agent_name = self.request.agent

    @property
    def request_id(self) -> str:
        """
        Runtime内部统一使用trace_id作为本次请求标识。
        """
        return self.trace_id

    def transition(
            self,
            status: RuntimeStatus
    ) -> None:
        """
        更新生命周期状态。
        """
        self.status = status

    def set_state(
            self,
            key: str,
            value: Any
    ):
        """
        保存运行状态
        """
        self.state[key] = value

    def get_state(
            self,
            key: str,
            default=None
    ):
        """
        获取运行状态
        """
        return self.state.get(
            key,
            default
        )

    def fail(
            self,
            error: Exception
    ):
        """
        标记失败
        """
        self.status = RuntimeStatus.FAILED
        self.error = error


    def success(
            self,
            response: Any
    ):
        """
        标记成功
        """
        self.status = RuntimeStatus.COMPLETED
        self.response = response


    def elapsed(
            self
    ):
        """
        获取耗时
        """
        return (
            time.time()
            -
            self.start_time
        )
