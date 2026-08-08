"""Runtime执行治理策略。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    """控制单次任务超时与允许重试次数。"""

    timeout_seconds: float | None = 300.0
    max_retries: int = 2

    def __post_init__(self) -> None:
        if (
            self.timeout_seconds is not None
            and self.timeout_seconds <= 0
        ):
            raise ValueError(
                "Runtime timeout_seconds must be positive."
            )
        if self.max_retries < 0:
            raise ValueError(
                "Runtime max_retries cannot be negative."
            )
