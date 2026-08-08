"""Bootstrap环境配置加载测试。"""

from pathlib import Path

import pytest
import yaml

from app.agent import AgentRegistry
from app.bootstrap.bootstrap import Bootstrap
from app.llm import (
    MeteredLLM,
    OpenAICompatibleLLM,
    RemoteInferenceEmbedding,
    RemoteInferenceRerankModel,
    ResilientLLM,
    StructuredOutputLLM,
)
from app.tool import ToolRegistry


def _write_yaml(path: Path, data: dict) -> None:
    """将测试配置写入pytest提供的临时目录。"""
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True),
        encoding="utf-8",
    )


def _environment_config(
        environment: str,
        *,
        host: str,
        log_level: str,
) -> dict:
    """生成满足BootstrapConfig校验要求的最小环境配置。"""
    return {
        "environment": environment,
        "host": host,
        "port": 8000,
        "log_level": log_level,
        "default_agent": "default",
        "models": {},
        "llm_agents": [],
    }


def test_loads_only_selected_test_environment(
    tmp_path: Path,
) -> None:
    """选择test时只使用config.test.yaml中的业务配置。"""
    selector = tmp_path / "config.yaml"
    _write_yaml(selector, {"environment": "test"})
    _write_yaml(
        tmp_path / "config.test.yaml",
        _environment_config(
            "test",
            host="127.0.0.1",
            log_level="DEBUG",
        ),
    )
    _write_yaml(
        tmp_path / "config.production.yaml",
        {
            # 如果错误加载生产配置，这个未知字段会使校验失败。
            "environment": "production",
            "unexpected_field": True,
        },
    )

    bootstrap = Bootstrap({"config_file": str(selector)})
    bootstrap._load_config()

    assert bootstrap.config["environment"] == "test"
    assert bootstrap.config["host"] == "127.0.0.1"
    assert bootstrap.config["log_level"] == "DEBUG"


def test_explicit_environment_overrides_selector(
    tmp_path: Path,
) -> None:
    """代码显式指定的环境优先于config.yaml中的环境。"""
    selector = tmp_path / "config.yaml"
    _write_yaml(selector, {"environment": "test"})
    _write_yaml(
        tmp_path / "config.production.yaml",
        _environment_config(
            "production",
            host="0.0.0.0",
            log_level="INFO",
        ),
    )

    bootstrap = Bootstrap(
        {
            "config_file": str(selector),
            "environment": "production",
        }
    )
    bootstrap._load_config()

    assert bootstrap.config["environment"] == "production"
    assert bootstrap.config["host"] == "0.0.0.0"


def test_production_safety_rejects_development_storage(
    tmp_path: Path,
) -> None:
    """生产环境必须在监听端口前拒绝SQLite等危险配置。"""
    selector = tmp_path / "config.yaml"
    _write_yaml(selector, {"environment": "production"})
    _write_yaml(
        tmp_path / "config.production.yaml",
        _environment_config(
            "production",
            host="0.0.0.0",
            log_level="INFO",
        ),
    )
    bootstrap = Bootstrap({"config_file": str(selector)})
    bootstrap._load_config()

    with pytest.raises(
        ValueError,
        match="Unsafe production configuration",
    ):
        bootstrap._validate_production_safety()


def test_explicit_bootstrap_value_overrides_environment_file(
    tmp_path: Path,
) -> None:
    """Bootstrap显式参数拥有最高配置优先级。"""
    selector = tmp_path / "config.yaml"
    _write_yaml(selector, {"environment": "test"})
    _write_yaml(
        tmp_path / "config.test.yaml",
        _environment_config(
            "test",
            host="127.0.0.1",
            log_level="DEBUG",
        ),
    )

    bootstrap = Bootstrap(
        {
            "config_file": str(selector),
            "host": "192.0.2.10",
        }
    )
    bootstrap._load_config()

    assert bootstrap.config["host"] == "192.0.2.10"


def test_database_url_environment_overrides_environment_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selector = tmp_path / "config.yaml"
    _write_yaml(selector, {"environment": "test"})
    config = _environment_config(
        "test",
        host="127.0.0.1",
        log_level="DEBUG",
    )
    config["system_database_url"] = "sqlite+aiosqlite:///from-file.db"
    _write_yaml(tmp_path / "config.test.yaml", config)
    database_url = "postgresql+asyncpg://ci@localhost/platform"
    monkeypatch.setenv("EAP_SYSTEM_DATABASE_URL", database_url)

    bootstrap = Bootstrap({"config_file": str(selector)})
    bootstrap._load_config()

    assert bootstrap.config["system_database_url"] == database_url


def test_rejects_unknown_environment(
    tmp_path: Path,
) -> None:
    """不允许使用未声明的运行环境。"""
    selector = tmp_path / "config.yaml"
    _write_yaml(selector, {"environment": "staging"})

    bootstrap = Bootstrap({"config_file": str(selector)})

    with pytest.raises(ValueError, match="Invalid environment"):
        bootstrap._load_config()


def test_requires_selected_environment_file(
    tmp_path: Path,
) -> None:
    """选中的环境配置不存在时必须阻止平台启动。"""
    selector = tmp_path / "config.yaml"
    _write_yaml(selector, {"environment": "test"})

    bootstrap = Bootstrap({"config_file": str(selector)})

    with pytest.raises(
        FileNotFoundError,
        match="Environment config file not found or empty",
    ):
        bootstrap._load_config()


def test_rejects_unknown_configuration_field(
    tmp_path: Path,
) -> None:
    """环境文件中的未知参数不能被静默忽略。"""
    selector = tmp_path / "config.yaml"
    _write_yaml(selector, {"environment": "test"})
    config = _environment_config(
        "test",
        host="127.0.0.1",
        log_level="DEBUG",
    )
    config["unknown_option"] = True
    _write_yaml(tmp_path / "config.test.yaml", config)

    bootstrap = Bootstrap({"config_file": str(selector)})

    with pytest.raises(
        ValueError,
        match="Invalid Bootstrap configuration",
    ):
        bootstrap._load_config()


def test_legacy_single_model_factory_returns_provider() -> None:
    """旧版api_key/model配置仍应创建OpenAI兼容Provider。"""
    bootstrap = Bootstrap()
    bootstrap.config = {
        "api_key": "test-key",
        "model": "legacy-model",
        "base_url": "https://example.invalid/v1",
    }

    provider = bootstrap._create_configured_llm()

    assert isinstance(provider, OpenAICompatibleLLM)
    assert provider.model_name == "legacy-model"


def test_remote_inference_profiles_build_http_adapters() -> None:
    bootstrap = Bootstrap()
    bootstrap.config = {
        "embedding_models": {
            "remote-embedding": {
                "provider": "platform_http",
                "model": "bge-m3",
                "endpoint": "http://inference:8100",
            }
        },
        "rerank_models": {
            "remote-reranker": {
                "provider": "platform_http",
                "model": "bge-reranker-large",
                "endpoint": "http://inference:8100",
            }
        },
    }

    embeddings = bootstrap._create_embedding_models()
    rerankers = bootstrap._create_rerank_models()

    assert isinstance(
        embeddings["remote-embedding"],
        RemoteInferenceEmbedding,
    )
    assert isinstance(
        rerankers["remote-reranker"],
        RemoteInferenceRerankModel,
    )


def test_model_profile_builds_resilient_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """模型Profile中的治理参数应自动包裹底层Provider。"""
    monkeypatch.setenv("TEST_MODEL_API_KEY", "test-key")
    bootstrap = Bootstrap()
    bootstrap.config = {
        "default_model": "logical-model",
        "models": {
            "logical-model": {
                "provider": "openai_compatible",
                "model": "provider-model",
                "api_key": None,
                "api_key_env": "TEST_MODEL_API_KEY",
                "base_url": "https://example.invalid/v1",
                "timeout_seconds": 12,
                "max_retries": 3,
                "backoff_base_seconds": 0.1,
                "backoff_max_seconds": 1,
                "circuit_failure_threshold": 4,
                "circuit_recovery_seconds": 20,
            }
        },
    }

    providers = bootstrap._create_configured_llms(None)
    provider = providers["logical-model"]

    assert isinstance(provider, StructuredOutputLLM)
    assert isinstance(provider.provider, MeteredLLM)
    metered = provider.provider
    assert isinstance(metered.provider, ResilientLLM)
    resilient = metered.provider
    assert isinstance(resilient.provider, OpenAICompatibleLLM)
    assert resilient.policy.timeout_seconds == 12
    assert resilient.policy.max_retries == 3
    assert resilient.policy.circuit_failure_threshold == 4


def test_bootstrap_registers_static_mcp_tool() -> None:
    """配置中的MCP工具应在不连接远端时进入ToolRegistry。"""
    application = Bootstrap(
        {
            "log_level": "CRITICAL",
            "mcp_servers": [
                {
                    "name": "crm",
                    "transport": "streamable_http",
                    "url": "https://mcp.example.invalid/mcp",
                    "tools": [
                        {
                            "name": "lookup",
                            "description": "Lookup CRM",
                            "input_schema": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"}
                                },
                                "required": ["id"],
                            },
                        }
                    ],
                }
            ],
        }
    ).build()

    registry = application.container.get(ToolRegistry)

    assert registry.exists("crm.lookup")
    assert registry.get("crm.lookup").schema().metadata["mcp"]


def test_bootstrap_registers_static_a2a_agent() -> None:
    """内联Agent Card应在启动时接入普通AgentRegistry。"""
    application = Bootstrap(
        {
            "log_level": "CRITICAL",
            "a2a_agents": [
                {
                    "name": "remote-support",
                    "card_url": (
                        "https://agent.example.invalid/"
                        ".well-known/agent-card.json"
                    ),
                    "card": {
                        "name": "Remote Support",
                        "description": "Support",
                        "version": "1.0.0",
                        "supportedInterfaces": [
                            {
                                "url": (
                                    "https://agent.example.invalid/rpc"
                                ),
                                "protocolBinding": "JSONRPC",
                                "protocolVersion": "1.0",
                            }
                        ],
                        "skills": [],
                    },
                }
            ],
        }
    ).build()

    registry = application.container.get(AgentRegistry)

    assert registry.exists("remote-support")
