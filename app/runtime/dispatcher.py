"""
Agent调度器

负责Runtime和Agent之间的调用。
"""

from app.agent import (
    AgentContext,  # Agent上下文
    AgentExecutor,  # Agent执行器
    AgentRegistry,  # Agent注册中心
    AgentResult,  # Agent结果
)


class AgentDispatcher:
    """
    Agent调度器。
    根据Agent名称执行对应任务。
    """

    def __init__(
            self,
            registry: AgentRegistry,
            executor: AgentExecutor
    ):
        # 保存Agent注册中心
        self.registry = registry

        # 保存Agent执行器
        self.executor = executor


    async def dispatch(
            self,
            agent_name: str,
            context: AgentContext
    ) -> AgentResult:
        """
        调度Agent执行。
        Args:
            agent_name:
                Agent名称
            context:
                Agent上下文
        Returns:
            Agent执行结果
        """

        # 1. 根据名称获取Agent
        agent = self.registry.get(
            agent_name,
            tenant_id=(
                str(context.metadata["tenant_id"])
                if context.metadata.get("tenant_id")
                else None
            ),
        )

        # 2. 交给Executor执行
        result = await self.executor.execute(
            agent,
            context
        )

        # 3. 返回执行结果
        return result
