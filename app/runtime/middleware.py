"""
Runtime中间件

负责在Agent执行前后处理公共逻辑。
"""
from abc import ABC

from app.runtime.context import RuntimeContext


class BaseMiddleware(
    ABC
):
    """
    中间件基类
    """
    async def before(
            self,
            context: RuntimeContext
    ) -> None:
        """
        执行前处理
        """
        pass

    async def after(
            self,
            context: RuntimeContext
    ) -> None:
        """
        执行后处理
        """
        pass

    async def on_error(
            self,
            context: RuntimeContext,
            error: Exception
    ) -> None:
        """
        异常处理
        """
        pass

class MiddlewareManager:
    """
    中间件管理器
    """
    def __init__(self):
        self.middlewares: list[
            BaseMiddleware
        ] = []

    def add(
            self,
            middleware: BaseMiddleware
    ) -> None:
        """
        添加中间件
        """
        self.middlewares.append(
            middleware
        )

    async def before(
            self,
            context: RuntimeContext
    ) -> list[BaseMiddleware]:
        """
        执行前置逻辑
        """
        entered: list[BaseMiddleware] = []

        try:
            for middleware in self.middlewares:
                await middleware.before(
                    context
                )
                entered.append(middleware)
        except Exception:
            context.set_state(
                "_entered_middlewares",
                entered
            )
            raise

        context.set_state(
            "_entered_middlewares",
            entered
        )
        return entered

    async def after(
            self,
            context: RuntimeContext
    ) -> None:
        """
        执行后置逻辑
        """
        entered = context.get_state(
            "_entered_middlewares",
            []
        )

        for middleware in reversed(entered):
            await middleware.after(
                context
            )

    async def on_error(
            self,
            context: RuntimeContext,
            error: Exception
    ) -> None:
        """
        异常处理
        """
        entered = context.get_state(
            "_entered_middlewares",
            []
        )

        for middleware in reversed(entered):
            await middleware.on_error(
                context,
                error
            )
