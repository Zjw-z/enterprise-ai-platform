"""
城市出行助手使用的天气查询 Tool。
"""

from app.tool import (
    BaseTool,
    ToolParameter,
    ToolPolicy,
    ToolResult,
    ToolSchema
)

class LearningWeatherTool(BaseTool):
    """ 根据城市返回可重复的学习用天气数据 """

    # 这是 Tool 在平台中的唯一名称。
    # Agent 配置和模型 Tool Call 都使用这个名称。
    name = "learning_get_weather"

    # ToolExecutor 最多等待10秒
    timeout = 10
    policy = ToolPolicy(
        parallel_safe=True,
        side_effects=False,
        idempotent=True,
    )

    def schema(self) -> ToolSchema:
        """ 向模型描述 Tool 的用途和输入参数。 """
        return ToolSchema(
            # Schema 名称必须和类属性 name 保持一致。
            name=self.name,
            # 描述越明确，模型越容易在正确调用Tool。
            description=(
                "查询指定中国城市的天气和温度。"
                "当用户询问天气、穿衣或出行建议时必须调用。"
            ),
            # 声明 Tool 接受的所有参数。
            parameters=[
                ToolParameter(
                    # 模型调用时传入的参数名称：{"city": "上海"}
                    name="city",

                    # 参数采用 JSON Schema 类型。
                    type="string",

                    # 告诉模型这个参数应该填写什么。
                    description="要查询的城市名称，例如上海、北京",

                    # 告诉模型这个参数是必须的。缺少参数时，ToolExecutor会拒绝执行。
                    required=True,
                )
            ]
        )

    async def run(self, params: dict) -> ToolResult:
        """ 执行天气查询并返回统一 ToolResult """
        # params 已经由 ToolExecutor 根据 Schema 校验过了。
        city = str(params.get("city")).strip()

        # 学习案例使用固定数据，保证评测结果可重复。
        # 正式业务可以在这里使用 httpx 调用真实天气服务。
        weather_by_city = {
            "上海": {
                "weather": "晴天", # 天气
                "temperature": 30, # 温度
                "rain_probability": 20 # 降水概率
            },
            "北京": {
                "weather": "阴天", # 天气
                "temperature": 20, # 温度
                "rain_probability": 50 # 降水概率
            },
            "广州": {
                "weather": "雨天",
                "temperature": 10,
                "rain_probability": 80
            }
        }

        # 未预置城市页返回结构稳定的默认结果。
        weather = weather_by_city.get(
            city,
            {
                "weather": "未知",
                "temperature": 25,
                "rain_probability": 0
            }
        )

        # 按照 ToolResult 结构返回结果。
        # ToolResult 是 ToolExecutor 的固定返回结果格式。
        return ToolResult(
            success=True, # 是否成功
            data={ # Tool返回数据
                "city": city, # 城市名称
                **weather, # 天气数据
                "source": "learning-weather-service", # 数据来源
            }
        )
