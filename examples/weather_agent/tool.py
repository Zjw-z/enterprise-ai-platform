"""
天气查询 Tool。

Tool只负责访问天气能力，不负责Prompt、路由或Agent决策。
"""

from app.tool import (
    BaseTool,  # 所有Tool的抽象基类
    ToolParameter,  # Tool参数定义
    ToolResult,  # Tool统一返回结果
    ToolSchema,  # Tool描述信息
)


class WeatherTool(BaseTool):
    """
    天气查询 Tool。
    """
    # 定义 Tool名称
    # AgentConfig和LLM ToolCall都通过该名称引用。
    name = "get_weather"

    # Tool调用超时时间，单位秒
    timeout = 5.0

    def schema(self) -> ToolSchema:
        """
        返回Tool描述信息。
        """
        """ Schema会被转换为LLM可理解的Function Calling格式 """
        return ToolSchema(
            name = self.name, # Tool名称
            description = "查询指定城市的天气",
            parameters = [
                ToolParameter( # Tool参数定义
                    name = "city", # 参数名称
                    type = "string", # 参数类型
                    description = "城市名称", # 参数描述
                    required = True, # 是否必填
                )
            ],
        )

    async def run(self, params: dict) -> ToolResult:
        # params已经经过ToolExecutor校验。

        # 获取参数值。
        city = params["city"]
        print("[WeatherTool] 正在查询：",city)

        # 学习阶段返回模拟数据。
        # 正式项目中在这里调用天气API。
        weather_data = {
            "city": city, # 城市名称
            "temperature": 25, # 温度
            "weather": "晴天", # 天气
        }

        # 返回Tool结果。必须返回ToolResult对象。
        return ToolResult(
            success=True, # 是否成功
            data = weather_data, # Tool返回数据
        )