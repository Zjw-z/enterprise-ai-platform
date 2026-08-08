"""multi-tool-trip-agent 的景点查询与预算计算 Tool。"""

from app.tool import (
    BaseTool,
    ToolParameter,
    ToolPolicy,
    ToolResult,
    ToolSchema,
)


class SearchCityAttractionsTool(BaseTool):
    """返回城市景点候选，固定数据保证评测可重复。"""

    name = "search_city_attractions"
    timeout = 10
    policy = ToolPolicy(
        parallel_safe=True,
        side_effects=False,
        idempotent=True,
    )

    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description="查询城市景点，用于目的地推荐和行程安排",
            parameters=[
                ToolParameter(
                    name="city",
                    type="string",
                    description="目的地城市，例如杭州、北京、上海",
                    required=True,
                ),
                ToolParameter(
                    name="days",
                    type="integer",
                    description="旅行天数",
                    required=True,
                    schema={"minimum": 1, "maximum": 14},
                ),
            ],
        )

    async def run(self, params: dict) -> ToolResult:
        city = str(params["city"]).strip()
        days = int(params["days"])
        attractions = {
            "杭州": ["西湖", "灵隐寺", "西溪湿地", "河坊街"],
            "北京": ["故宫", "天坛", "颐和园", "长城"],
            "上海": ["外滩", "上海博物馆", "豫园", "陆家嘴"],
        }.get(city, ["城市博物馆", "历史街区", "城市公园"])
        return ToolResult(
            success=True,
            data={
                "city": city,
                "days": days,
                "attractions": attractions[:max(2, days + 1)],
                "source": "demo-attraction-catalog",
            },
        )


class CalculateTripBudgetTool(BaseTool):
    """按照人数、天数和消费档次计算旅行预算。"""

    name = "calculate_trip_budget"
    timeout = 10
    policy = ToolPolicy(
        parallel_safe=True,
        side_effects=False,
        idempotent=True,
    )

    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description="计算住宿、餐饮、市内交通和门票预算",
            parameters=[
                ToolParameter(
                    name="days",
                    type="integer",
                    description="旅行天数",
                    required=True,
                    schema={"minimum": 1, "maximum": 30},
                ),
                ToolParameter(
                    name="people",
                    type="integer",
                    description="出行人数",
                    required=True,
                    schema={"minimum": 1, "maximum": 50},
                ),
                ToolParameter(
                    name="level",
                    type="string",
                    description="消费档次：经济、舒适或品质",
                    required=True,
                    schema={"enum": ["经济", "舒适", "品质"]},
                ),
            ],
        )

    async def run(self, params: dict) -> ToolResult:
        days = int(params["days"])
        people = int(params["people"])
        level = str(params["level"])
        daily = {
            "经济": {
                "hotel": 220,
                "meal": 100,
                "transport": 50,
                "ticket": 80,
            },
            "舒适": {
                "hotel": 420,
                "meal": 180,
                "transport": 100,
                "ticket": 150,
            },
            "品质": {
                "hotel": 800,
                "meal": 320,
                "transport": 220,
                "ticket": 260,
            },
        }[level]
        breakdown = {
            name: amount * days * people
            for name, amount in daily.items()
        }
        return ToolResult(
            success=True,
            data={
                "days": days,
                "people": people,
                "level": level,
                "currency": "CNY",
                "breakdown": breakdown,
                "total": sum(breakdown.values()),
            },
        )
