"""learning-travel-agent 使用的可重复天气 Tool。"""

from app.tool import (
    BaseTool,
    ToolParameter,
    ToolPolicy,
    ToolResult,
    ToolSchema,
)


class LearningWeatherTool(BaseTool):
    """根据城市返回可重复数据，方便 Agent 回归评测。"""

    name = "learning_get_weather"
    timeout = 10
    policy = ToolPolicy(
        parallel_safe=True,
        side_effects=False,
        idempotent=True,
    )

    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description=(
                "查询指定中国城市的天气和温度。"
                "当用户询问天气、穿衣或出行建议时使用。"
            ),
            parameters=[
                ToolParameter(
                    name="city",
                    type="string",
                    description="要查询的城市名称，例如上海、北京",
                    required=True,
                )
            ],
        )

    async def run(self, params: dict) -> ToolResult:
        city = str(params["city"]).strip()
        weather = {
            "上海": {
                "weather": "晴天",
                "temperature": 30,
                "rain_probability": 20,
            },
            "北京": {
                "weather": "阴天",
                "temperature": 20,
                "rain_probability": 50,
            },
            "广州": {
                "weather": "雨天",
                "temperature": 10,
                "rain_probability": 80,
            },
        }.get(city, {
            "weather": "未知",
            "temperature": 25,
            "rain_probability": 0,
        })
        return ToolResult(
            success=True,
            data={
                "city": city,
                **weather,
                "source": "learning-weather-service",
            },
        )
