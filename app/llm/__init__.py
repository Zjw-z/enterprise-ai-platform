"""
LLM模块统一出口

对外暴露LLM相关组件。
"""
from .base import BaseLLM  # LLM抽象接口
from .capabilities import (
    BaseEmbeddingModel,
    BaseRerankModel,
    EmbeddingRequest,
    EmbeddingResponse,
    LexicalRerankModel,
    LocalCrossEncoderRerankModel,
    LocalSentenceTransformerEmbedding,
    OpenAICompatibleEmbedding,
    RemoteInferenceEmbedding,
    RemoteInferenceRerankModel,
    RerankRequest,
    RerankResponse,
    RerankResult,
)
from .configuration import ModelProfileService, ModelRuntimeLoader
from .manager import LLMManager  # LLM管理器
from .openai import OpenAICompatibleLLM  # OpenAI兼容实现
from .provider import LLMProviderFactory, ProviderBuilder
from .resilience import (
    CircuitState,
    LLMResiliencePolicy,
    ResilientLLM,
)
from .routing import RoutingLLM, RoutingStrategy
from .schema import (
    ChatMessage,  # 对话消息结构
    LLMRequest,  # LLM请求结构
    LLMResponse,  # LLM响应结构
    StreamChunk,  # 流式输出结构
    TokenUsage,  # Token统计结构
)
from .structured import StructuredOutputLLM, validate_json_value
from .usage import (
    LLMUsageManager,
    LLMUsageRecord,
    MeteredLLM,
    ModelPricing,
    TokenReservation,
)
from .usage_store import LLMUsageStore

__all__ = [
    "ChatMessage",  # 消息结构
    "LLMRequest",  # 请求结构
    "LLMResponse",  # 响应结构
    "TokenUsage",  # Token统计
    "StreamChunk",  # 流式数据

    "BaseLLM",  # LLM接口
    "ModelProfileService",
    "ModelRuntimeLoader",

    "OpenAICompatibleLLM",  # OpenAI兼容模型

    "LLMManager",  # LLM管理
    "CircuitState",
    "LLMResiliencePolicy",
    "ResilientLLM",
    "LLMProviderFactory",
    "ProviderBuilder",
    "RoutingLLM",
    "RoutingStrategy",
    "LLMUsageManager",
    "LLMUsageStore",
    "LLMUsageRecord",
    "MeteredLLM",
    "ModelPricing",
    "TokenReservation",
    "StructuredOutputLLM",
    "validate_json_value",
    "BaseEmbeddingModel",
    "BaseRerankModel",
    "EmbeddingRequest",
    "EmbeddingResponse",
    "LexicalRerankModel",
    "LocalCrossEncoderRerankModel",
    "LocalSentenceTransformerEmbedding",
    "OpenAICompatibleEmbedding",
    "RemoteInferenceEmbedding",
    "RemoteInferenceRerankModel",
    "RerankRequest",
    "RerankResponse",
    "RerankResult",
]
