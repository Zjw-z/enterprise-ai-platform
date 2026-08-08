"""
Runtime执行器。

负责将Runtime上下文转换为Agent上下文，并交给Dispatcher执行。
"""
from app.agent import AgentContext, AgentResult
from app.core.exceptions import ExecuteError
from app.runtime.context import RuntimeContext, RuntimeStatus
from app.runtime.dispatcher import AgentDispatcher


class Executor:
    """
    Runtime执行器。

    不直接创建或执行Agent，Agent选择和执行分别交给
    AgentDispatcher与AgentExecutor。
    """

    def __init__(
            self,
            dispatcher: AgentDispatcher
    ):
        self.dispatcher = dispatcher

    async def execute(
            self,
            runtime_context: RuntimeContext
    ) -> AgentResult:
        """
        执行Agent
        Args:
            runtime_context:
                Runtime上下文
        """
        try:
            runtime_context.transition(
                RuntimeStatus.RUNNING
            )

            agent_context = AgentContext(
                request_id=runtime_context.request_id,
                session_id=(
                    runtime_context.request.session_id
                    or ""
                ),
                user_input=runtime_context.request.message,
                user_id=runtime_context.request.user_id,
                variables=dict(
                    runtime_context.request.parameters
                ),
                metadata=dict(
                    runtime_context.request.metadata
                )
            )

            runtime_context.set_state(
                "agent_context",
                agent_context
            )

            result = await self.dispatcher.dispatch(
                runtime_context.agent_name,
                agent_context
            )

            if not result.success:
                raise ExecuteError(
                    result.error
                    or "Agent execution failed."
                )

            runtime_context.success(
                result
            )
            return result

        except Exception as e:
            runtime_context.fail(
                e
            )

            raise
