"""
LLM抽象基类

定义所有大模型调用实现必须遵循的接口。
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from app.llm.schema import LLMRequest, LLMResponse, StreamChunk


class BaseLLM(
    ABC
):
    """
    LLM基础抽象类。
    所有模型Provider必须继承该类。
    """


    def __init__(
            self,
            model_name: str
    ):
        # 当前模型名称
        self.model_name = model_name


    @abstractmethod
    async def chat(
            self,
            request: LLMRequest
    ) -> LLMResponse:
        """
        普通模型调用。
        Args:
            request:
                LLM请求参数
        Returns:
            LLM响应结果
        """

        pass


    @abstractmethod
    async def stream(
            self,
            request: LLMRequest
    ) -> AsyncIterator[StreamChunk]:
        """
        流式模型调用。
        Args:
            request:
                LLM请求参数
        Returns:
            流式数据生成器
        """
        pass


    def info(
            self
    ) -> dict[str, Any]:
        """
        获取模型信息。
        用于:
        - 日志记录
        - 模型管理
        - 监控统计
        """
        return {
            "model_name": self.model_name  # 返回模型名称
        }

    def health(self) -> dict[str, Any]:
        """
        返回不触发真实推理调用的被动健康快照。

        Provider可覆盖该方法并基于连接池、熔断器或最近调用结果给出状态。
        """
        return {
            "status": "available",
            "model_name": self.model_name,
        }
