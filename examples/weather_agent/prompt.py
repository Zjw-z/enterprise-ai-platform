"""
天气Agent使用的 Prompt资源。

Prompt独立于Agent和Tool，由PromptRegistry统一管理。
"""
from app.prompt import (
    PromptTemplate,  # Prompt数据结构定义
    PromptVariable,  # Prompt变量定义
)

# 天气Prompt
WEATHER_PROMPT = PromptTemplate(
    name = "weather-agent-system", # Prompt名称
    version="1.0", # Prompt版本
    description="天气Prompt", # Prompt描述，用途说明
    template=(
        "你是{company}的天气助手。"
        "回答天气问题前必须调用天气工具。"
    ), # Prompt模板

    # 声明模板中允许使用的变量。
    # PromptRenderer会使用variables替换模板变量。
    variables=[ # Prompt变量
        PromptVariable(
            name="company", # 变量名称
            default="万达信息", # 示例公司
            description="公司名称", # 变量的描述信息
            required=True, # 是否必填
        )
    ],
)