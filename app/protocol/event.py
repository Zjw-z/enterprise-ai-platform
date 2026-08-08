"""
平台事件协议

定义 AI 平台内部事件对象。

用于：

- Runtime 生命周期
- Agent执行过程
- Tool调用
- LLM调用
- Streaming输出
- Trace追踪
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(slots=True)
class Event:
    """
    平台内部事件对象
    """

    # 事件唯一ID
    id: str = field(
        default_factory=lambda: str(uuid.uuid4())
    )

    # 事件类型
    type: str = ""

    # 事件来源
    source: str = ""

    # 创建时间
    timestamp: datetime = field(
        default_factory=lambda:
        datetime.now(UTC)
    )

    # 事件数据
    data: dict[str, Any] = field(
        default_factory=dict
    )

    # 扩展信息
    metadata: dict[str, Any] = field(
        default_factory=dict
    )