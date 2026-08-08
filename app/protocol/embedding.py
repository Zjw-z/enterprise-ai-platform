"""
Embedding协议

定义平台统一向量化接口的数据结构。

用于：

- RAG
- Knowledge Base
- Memory
- Vector Search
- Multimodal Retrieval
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class EmbeddingRequest:
    """
    向量化请求
    """

    # 输入文本列表
    texts: list[str]

    # 指定模型（可选）
    model: str | None = None

    # 额外参数
    metadata: dict[str, Any] = field(
        default_factory=dict
    )


@dataclass(slots=True)
class EmbeddingResponse:
    """
    向量化响应
    """

    # 向量结果
    vectors: list[list[float]]

    # 使用模型
    model: str | None = None

    # 向量维度
    dimension: int = 0

    # Token数量
    token_usage: int = 0

    # 扩展信息
    metadata: dict[str, Any] = field(
        default_factory=dict
    )