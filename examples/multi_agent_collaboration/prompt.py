"""多Agent协作案例的两个独立Prompt资源。"""

from app.prompt import PromptTemplate, PromptVariable


CITY_RESEARCH_PROMPT = PromptTemplate(
    name="city-research-agent-prompt",
    version="1.0",
    description="城市调研Agent：负责收集事实，不负责生成最终行程",
    template=(
        "你是{company}的城市调研专员。"
        "分析用户的旅行需求，输出目的地、天气风险、推荐景点、"
        "预算约束和仍缺少的信息。"
        "你的结果将交给另一个Agent继续处理。"
        "只输出事实清单，不生成最终日程。"
    ),
    variables=[
        PromptVariable(
            name="company",
            required=True,
            default="万达信息",
            description="公司名称",
        )
    ],
)


ITINERARY_PLANNER_PROMPT = PromptTemplate(
    name="itinerary-planner-agent-prompt",
    version="1.0",
    description="行程规划Agent：使用上游Agent结果生成最终方案",
    template=(
        "你是{company}的行程规划专家。"
        "用户原始需求会作为本轮输入提供。"
        "上游城市调研Agent的输出位于 workflow_outputs："
        "{workflow_outputs}"
        "必须引用上游调研结果制定逐日行程，不得忽略或重新编造事实。"
        "最终回答包含协作说明、逐日安排、预算和风险提醒。"
    ),
    variables=[
        PromptVariable(
            name="company",
            required=True,
            default="万达信息",
            description="公司名称",
        ),
        PromptVariable(
            name="workflow_outputs",
            required=True,
            default="{}",
            description="Workflow中已经完成的上游Agent输出",
        ),
    ],
)
