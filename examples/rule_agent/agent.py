"""
规则型 Agent

这个文件只放Agent业务逻辑，不负责平台启动、HTTP路由或组件注册。
"""

from app.agent import (
    AgentConfig,  # Agent静态配置
    AgentContext,  # 一次Agent请求的上下文
    AgentResult,  # Agent统一返回对象
    BaseAgent,  # 自定义Agent必须继承的抽象基类
)


class RuleAgent(BaseAgent):
    """
    一个完全不依赖LLM的规则型Agent。

    适合固定规则、审批判断、参数转换等确定性业务。
    """

    async def execute(
            self,
            context: AgentContext
    ) -> AgentResult:
        # context.user_input来自HTTP请求中的message字段
        user_input = context.user_input

        # 输出当前请求ID，观察Runtime到Agent的数据传递。
        print("[RuleAgent] request_id =", context.request_id)

        # 输出Agent收到的原始用户输入
        print("[RuleAgent] user_input =", user_input)

        # 这里是Agent真正的业务判断
        if "你好" in user_input:
            content = "你好，我是规则型Agent。"

        elif "订单" in user_input:
            content = "订单请求已经收到，正在进入处理流程。"

        else:
            content = "规则Agent暂时无法识别该请求：" + user_input

        # Agent必须返回平台统一的AgentResult。
        return AgentResult(
            success=True, # 表示业务执行成功
            content=content, # API最终返回的主要文本内容
            metadata={
                # metadata可用于携带额外业务信息
                "agent_type": "rule", # Agent类型
                "request_id": context.request_id, # 请求ID
            },
        )

# 这里只创建Agent实例，不启动平台
RULE_AGENT = RuleAgent(
    AgentConfig(
        # Agent唯一名称
        # 请求中的agent字段和Dispatcher都使用这个名称。
        name="rule-agent",

        # Agent说明，可用于日志、管理后台和组件发现。
        description="规则型Agent",

        # 规则Agent不使用平台Memory。
        memory_enabled=False,
    )
)