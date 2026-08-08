"""Runtime输入输出内容安全中间件。"""

from app.agent import AgentResult
from app.core.content_safety import ContentSafetyManager
from app.runtime.context import RuntimeContext
from app.runtime.middleware import BaseMiddleware


class ContentSafetyMiddleware(BaseMiddleware):
    """在Agent执行前检查输入，执行后检查最终文本输出。"""

    def __init__(
        self,
        manager: ContentSafetyManager,
    ) -> None:
        self.manager = manager

    async def before(
        self,
        context: RuntimeContext,
    ) -> None:
        self.manager.validate_input(
            context.request.message
        )

    async def after(
        self,
        context: RuntimeContext,
    ) -> None:
        if isinstance(context.response, AgentResult):
            self.manager.validate_output(
                context.response.content
            )
