"""
Runtime流式管理
负责处理 AI 平台流式事件。
支持：
- LLM Token流
- Agent状态流
- Tool执行流
- SSE/WebSocket扩展
"""

from collections.abc import AsyncIterator

from app.protocol.event import Event


class StreamManager:
    """
    流式输出管理器
    """
    async def stream(
            self,
            events: AsyncIterator[Event]
    ) -> AsyncIterator[Event]:
        """
        转发事件流
        Args:
            events:
                事件生成器
        Yields:
            Event
        """
        async for event in events:

            yield event