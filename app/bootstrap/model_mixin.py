"""Bootstrap 模型与远程 Tool Adapter 构造逻辑。"""

from __future__ import annotations

import logging
from pathlib import Path

from app.llm import (
    BaseLLM,
    LexicalRerankModel,
    LLMProviderFactory,
    LLMResiliencePolicy,
    LLMUsageManager,
    LocalCrossEncoderRerankModel,
    LocalSentenceTransformerEmbedding,
    MeteredLLM,
    ModelPricing,
    OpenAICompatibleEmbedding,
    RemoteInferenceEmbedding,
    RemoteInferenceRerankModel,
    ResilientLLM,
    RoutingLLM,
    RoutingStrategy,
    StructuredOutputLLM,
)
from app.tool import RemoteHTTPTool, ToolPolicy

logger = logging.getLogger(__name__)


class BootstrapModelMixin:
    """构造聊天、Embedding、Rerank 模型与远程 Tool。"""

    def _create_configured_llms(
            self,
            injected_llm: BaseLLM | None,
            usage_manager: LLMUsageManager | None = None,
    ) -> dict[str, BaseLLM]:
        """
        根据模型Profile创建多个Provider。

        返回值的key是平台逻辑模型名，AgentConfig只依赖这个名称。
        """
        profiles = self.config.get("models", {})

        if not profiles:
            provider = (
                injected_llm
                or self._create_configured_llm()
            )
            return (
                {provider.model_name: provider}
                if provider is not None
                else {}
            )

        if injected_llm is not None:
            registry_name = str(
                self.config.get(
                    "default_model",
                    injected_llm.model_name
                )
            )
            return {registry_name: injected_llm}

        providers: dict[str, BaseLLM] = {}
        default_name = self.config.get("default_model")
        usage_manager = usage_manager or LLMUsageManager()
        provider_factory = LLMProviderFactory()
        for provider_type, builder in self.config.get(
                "llm_provider_factories",
                {},
        ).items():
            provider_factory.register(
                str(provider_type),
                builder,
            )

        for registry_name, profile in profiles.items():
            if not isinstance(profile, dict):
                raise TypeError(
                    f"Model profile '{registry_name}' must be a mapping."
                )

            provider_name = profile.get(
                "provider",
                "openai_compatible"
            )
            api_key_env = profile.get(
                "api_key_env",
                "DASHSCOPE_API_KEY"
            )

            if str(api_key_env).startswith("sk-"):
                raise ValueError(
                    f"Model profile '{registry_name}' has an API key "
                    "under api_key_env. Use api_key for a local secret "
                    "or set api_key_env to an environment variable name."
                )

            # 允许本地未提交配置直接保存api_key，
            # 但生产环境仍建议使用环境变量或Secret Manager。
            configured_api_key = profile.get("api_key")
            if configured_api_key in {
                    None,
                    "",
                    "REPLACE_WITH_NEW_DASHSCOPE_API_KEY",
            }:
                configured_api_key = None

            api_key = self.secret_manager.resolve(
                direct_value=configured_api_key,
                secret_name=str(api_key_env),
            )
            if not api_key:
                logger.warning(
                    "Skipping model profile '%s': missing "
                    "API key environment variable '%s'.",
                    registry_name,
                    api_key_env,
                )
                continue

            base_url_env = profile.get("base_url_env")
            base_url = self.secret_manager.resolve(
                direct_value=profile.get("base_url"),
                secret_name=(
                    str(base_url_env)
                    if base_url_env
                    else None
                ),
            )

            provider = provider_factory.create(
                str(provider_name),
                model_name=str(profile["model"]),
                api_key=api_key,
                base_url=base_url,
                default_temperature=float(
                    profile.get("temperature", 0.7)
                ),
                default_max_tokens=(
                    int(profile["max_tokens"])
                    if profile.get("max_tokens") is not None
                    else None
                ),
            )
            policy = LLMResiliencePolicy(
                timeout_seconds=float(
                    profile.get("timeout_seconds", 60.0)
                ),
                max_retries=int(
                    profile.get("max_retries", 2)
                ),
                backoff_base_seconds=float(
                    profile.get("backoff_base_seconds", 0.25)
                ),
                backoff_max_seconds=float(
                    profile.get("backoff_max_seconds", 5.0)
                ),
                circuit_failure_threshold=int(
                    profile.get("circuit_failure_threshold", 5)
                ),
                circuit_recovery_seconds=float(
                    profile.get("circuit_recovery_seconds", 30.0)
                ),
            )
            providers[str(registry_name)] = StructuredOutputLLM(
                MeteredLLM(
                    ResilientLLM(
                        provider,
                        policy,
                    ),
                    logical_model=str(registry_name),
                    usage_manager=usage_manager,
                    pricing=ModelPricing(
                        input_per_million=float(
                            profile.get(
                                "input_cost_per_million",
                                0.0,
                            )
                        ),
                        output_per_million=float(
                            profile.get(
                                "output_cost_per_million",
                                0.0,
                            )
                        ),
                    ),
                    default_max_tokens=int(
                        profile.get("max_tokens") or 4096
                    ),
                ),
            )

        for route_name, route in self.config.get(
                "model_routes",
                {},
        ).items():
            normalized_name = str(route_name)
            if normalized_name in providers:
                raise ValueError(
                    f"Model route conflicts with profile: "
                    f"{normalized_name}"
                )
            member_names = [
                str(name)
                for name in route.get("models", [])
            ]
            missing = [
                name
                for name in member_names
                if name not in providers
            ]
            if missing:
                raise ValueError(
                    f"Model route '{normalized_name}' references "
                    f"unknown profiles: {missing}"
                )
            providers[normalized_name] = RoutingLLM(
                model_name=normalized_name,
                providers=[
                    providers[name]
                    for name in member_names
                ],
                strategy=RoutingStrategy(
                    route.get("strategy", "failover")
                ),
            )

        if (
                providers
                and default_name
                and default_name not in providers
        ):
            raise ValueError(
                f"Default model profile does not exist: {default_name}"
            )

        return providers

    def _create_embedding_models(self) -> dict:
        """从统一配置创建Embedding模型。"""
        # 返回值以逻辑Profile名称为键，Knowledge和Memory不依赖具体Provider。
        result = {}
        for registry_name, profile in self.config.get(
                "embedding_models",
                {},
        ).items():
            provider = profile.get("provider", "openai_compatible")
            # platform_http把GPU模型放在独立推理进程，API仅通过HTTP调用。
            if provider == "platform_http":
                result[str(registry_name)] = RemoteInferenceEmbedding(
                    model_name=str(profile["model"]),
                    endpoint=str(profile["endpoint"]),
                    api_key=self.secret_manager.resolve(
                        direct_value=profile.get("api_key"),
                        secret_name=profile.get("api_key_env"),
                    ),
                    timeout_seconds=float(
                        profile.get("timeout_seconds", 60.0)
                    ),
                )
                continue
            # sentence_transformers适合本机或独立推理服务加载本地模型目录。
            if provider == "sentence_transformers":
                model_path = Path(str(profile["model_path"]))
                if not model_path.is_absolute():
                    model_path = (
                        Path(__file__).resolve().parents[2] / model_path
                    )
                if not model_path.is_dir():
                    raise ValueError(
                        f"Embedding model path does not exist: {model_path}"
                    )
                result[str(registry_name)] = (
                    LocalSentenceTransformerEmbedding(
                        model_name=str(profile["model"]),
                        model_path=str(model_path),
                        device=profile.get("device"),
                        batch_size=int(profile.get("batch_size", 16)),
                        normalize_embeddings=bool(
                            profile.get("normalize_embeddings", True)
                        ),
                    )
                )
                continue
            if provider != "openai_compatible":
                raise ValueError(
                    "Unsupported embedding provider: "
                    f"{profile.get('provider')}"
                )
            # 其余Profile按OpenAI Compatible Embedding协议创建。
            api_key = self.secret_manager.resolve(
                direct_value=profile.get("api_key"),
                secret_name=str(
                    profile.get(
                        "api_key_env",
                        "DASHSCOPE_API_KEY",
                    )
                ),
            )
            if not api_key:
                logger.warning(
                    "Skipping embedding profile '%s': missing API key.",
                    registry_name,
                )
                continue
            base_url_env = profile.get("base_url_env")
            base_url = self.secret_manager.resolve(
                direct_value=profile.get("base_url"),
                secret_name=(
                    str(base_url_env)
                    if base_url_env
                    else None
                ),
            )
            result[str(registry_name)] = (
                OpenAICompatibleEmbedding(
                    model_name=str(profile["model"]),
                    api_key=api_key,
                    base_url=base_url,
                    default_dimensions=profile.get(
                        "dimensions"
                    ),
                )
            )
        return result

    def _create_rerank_models(self) -> dict:
        """从统一配置创建Rerank模型。"""
        # Rerank与Embedding分别注册，允许独立扩容和选择不同设备。
        result = {}
        for registry_name, profile in self.config.get(
                "rerank_models",
                {},
        ).items():
            provider = profile.get("provider", "lexical")
            # 远程推理Adapter避免API进程重复加载大模型。
            if provider == "platform_http":
                result[str(registry_name)] = (
                    RemoteInferenceRerankModel(
                        model_name=str(profile["model"]),
                        endpoint=str(profile["endpoint"]),
                        api_key=self.secret_manager.resolve(
                            direct_value=profile.get("api_key"),
                            secret_name=profile.get("api_key_env"),
                        ),
                        timeout_seconds=float(
                            profile.get("timeout_seconds", 60.0)
                        ),
                    )
                )
                continue
            # CrossEncoder使用本地bge-reranker等模型进行候选文本精排。
            if provider == "cross_encoder":
                model_path = Path(str(profile["model_path"]))
                if not model_path.is_absolute():
                    model_path = (
                        Path(__file__).resolve().parents[2] / model_path
                    )
                if not model_path.is_dir():
                    raise ValueError(
                        f"Rerank model path does not exist: {model_path}"
                    )
                result[str(registry_name)] = (
                    LocalCrossEncoderRerankModel(
                        model_name=str(profile["model"]),
                        model_path=str(model_path),
                        device=profile.get("device"),
                        batch_size=int(profile.get("batch_size", 16)),
                        max_length=int(profile.get("max_length", 512)),
                    )
                )
                continue
            if provider != "lexical":
                raise ValueError(
                    f"Unsupported rerank provider: {provider}"
                )
            # lexical是无GPU环境的确定性兜底实现。
            result[str(registry_name)] = LexicalRerankModel(
                str(profile.get("model", "lexical-v1"))
            )
        return result

    def _create_remote_tools(self) -> list[RemoteHTTPTool]:
        """把YAML远程Tool声明转换为受沙箱治理的Tool实例。"""
        # 每个声明都转换为统一BaseTool，随后与Python/MCP Tool共同注册。
        result: list[RemoteHTTPTool] = []
        for raw in self.config.get("remote_tools", []):
            endpoint = str(raw["endpoint"])
            from urllib.parse import urlparse

            # 提取并固定目标域名，网络沙箱只允许访问声明的Tool主机。
            host = urlparse(endpoint).hostname
            if not host:
                raise ValueError(
                    f"Invalid remote tool endpoint: {endpoint}"
                )
            # 非敏感Header可直接配置，认证Header从环境变量补充。
            headers = dict(raw.get("headers", {}))
            for header, secret_name in raw.get(
                    "header_env",
                    {},
            ).items():
                value = self.secret_manager.get(
                    str(secret_name)
                )
                if not value:
                    raise ValueError(
                        f"Remote tool '{raw['name']}' missing "
                        f"header secret: {secret_name}"
                    )
                headers[str(header)] = value
            # ToolPolicy同时描述租户/角色授权、重试、结果上限和审批要求。
            tool = RemoteHTTPTool(
                name=str(raw["name"]),
                description=str(
                    raw.get("description", "")
                ),
                endpoint=endpoint,
                input_schema=dict(raw["input_schema"]),
                headers=headers,
                policy=ToolPolicy(
                    allowed_tenants=frozenset(
                        raw.get("allowed_tenants", ["*"])
                    ),
                    required_roles=frozenset(
                        raw.get("required_roles", [])
                    ),
                    max_retries=int(
                        raw.get("max_retries", 1)
                    ),
                    max_result_bytes=int(
                        raw.get(
                            "max_result_bytes",
                            1_048_576,
                        )
                    ),
                    risk_level=str(
                        raw.get("risk_level", "medium")
                    ),
                    approval_required=bool(
                        raw.get(
                            "approval_required",
                            False,
                        )
                    ),
                    approval_roles=frozenset(
                        raw.get(
                            "approval_roles",
                            ["tool_approver"],
                        )
                    ),
                    sandbox_required=True,
                    network_access=True,
                    allowed_network_domains=(host,),
                    io_timeout_seconds=float(
                        raw.get("timeout_seconds", 30.0)
                    ),
                ),
            )
            tool.timeout = float(
                raw.get("timeout_seconds", 30.0)
            )
            result.append(tool)
        return result
