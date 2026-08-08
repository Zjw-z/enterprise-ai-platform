"""weather-agent 的天气查询 Tool。"""

from app.tool import (
    BaseTool,
    ToolParameter,
    ToolPolicy,
    ToolResult,
    ToolSchema,
)


class WeatherTool(BaseTool):
    """返回结构稳定的天气数据；生产环境可替换为真实天气适配器。"""

    name = "get_weather"
    timeout = 5.0
    policy = ToolPolicy(
        parallel_safe=True,
        side_effects=False,
        idempotent=True,
    )

    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description="查询指定城市的天气、温度和降水概率",
            parameters=[
                ToolParameter(
                    name="city",
                    type="string",
                    description="城市名称",
                    required=True,
                )
            ],
        )

    async def run(self, params: dict) -> ToolResult:
        city = str(params["city"]).strip()
        return ToolResult(
            success=True,
            data={
                "city": city,
                "temperature": 25,
                "weather": "晴天",
                "rain_probability": 0,
                "source": "weather-agent-demo-adapter",
            },
        )
