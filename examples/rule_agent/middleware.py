"""
用于观察 Runtime 生命周期的调试中间件
"""
from app.runtime import (
    BaseMiddleware,  # 所有Runtime中间件的基类
    RuntimeContext,  # 一次请求的Runtime上下文
)


class DebugMiddleware(BaseMiddleware):
    """
    打印请求进入、成功离开和异常离开的状态。
    """

    # before：运行时进入，请求处理之前调用
    async def before(
            self,
            context: RuntimeContext
    ) -> None:
        # before 发生在Agent执行之前。
        print("[Middleware.before]",
              "request_id = ",context.request_id,
              "status = ", context.status
              )

    # after：运行时离开，请求处理完成之后调用
    async def after(
            self,
            context: RuntimeContext
    ) -> None:
        # after 发生在Agent执行之后。
        print("[Middleware.after]",
              "request_id = ",context.request_id,
              "status = ", context.status
              )

    # exception：运行时异常，请求处理过程中发生异常调用
    async def on_error(
            self,
            context: RuntimeContext,
            error: Exception
    ) -> None:
        # on_error 发生在Agent执行过程中发生异常。
        print("[Middleware.on_error]",
              "request_id = ",context.request_id,
              "status = ", context.status,
              "error = ", error
              )