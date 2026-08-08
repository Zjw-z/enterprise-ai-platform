"""Bootstrap 的配置加载、安全校验与 Secret 组装。"""

import logging
import os
from pathlib import Path
from typing import Any

import yaml

from app.agent import AgentConfig
from app.bootstrap.config import BootstrapConfig
from app.core.logging_context import configure_logging
from app.core.secrets import (
    CachedSecretProvider,
    EnvironmentSecretProvider,
    MountedFileSecretProvider,
    SecretManager,
    VaultKV2SecretProvider,
)

logger = logging.getLogger(__name__)


class BootstrapConfigurationMixin:
    """向 Bootstrap 提供配置阶段实现，外部不直接实例化。"""

    def _configure_secret_manager(self) -> None:
        """按配置顺序组装Secret Adapter；外部Provider统一增加TTL缓存。"""
        providers = []
        ttl = float(self.config.get("secret_cache_ttl_seconds", 60.0))
        for provider_name in self.config.get("secret_provider_order", ["environment"]):
            if provider_name == "environment":
                providers.append(EnvironmentSecretProvider())
            elif provider_name == "mounted_file":
                directory = self.config.get("mounted_secret_directory")
                if directory:
                    providers.append(
                        CachedSecretProvider(
                            MountedFileSecretProvider(str(directory)),
                            ttl_seconds=ttl,
                        )
                    )
            elif provider_name == "vault" and self.config.get("vault_enabled", False):
                token = os.getenv(
                    str(self.config.get("vault_token_env", "VAULT_TOKEN"))
                )
                address = self.config.get("vault_address")
                if token and address:
                    providers.append(
                        CachedSecretProvider(
                            VaultKV2SecretProvider(
                                address=str(address),
                                token=token,
                                mount=str(self.config.get("vault_mount", "secret")),
                                path_prefix=str(
                                    self.config.get(
                                        "vault_path_prefix",
                                        "enterprise-ai",
                                    )
                                ),
                                namespace=self.config.get("vault_namespace"),
                            ),
                            ttl_seconds=ttl,
                        )
                    )
        if not providers:
            raise ValueError("No configured Secret Provider is available.")
        self.secret_manager = SecretManager(providers)

    def _validate_production_safety(self) -> None:
        """生产环境在创建任何外部连接前拒绝危险配置。"""
        # 测试环境允许内存Store和宽松Origin，生产环境才启用以下强约束。
        if self.config.get("environment") != "production":
            return
        # 一次性收集全部错误，便于运维人员单次修改完所有不安全配置。
        errors: list[str] = []
        # 企业运行数据必须使用支持事务和并发控制的PostgreSQL异步驱动。
        database_url = str(self.config.get("system_database_url", ""))
        if not database_url.startswith("postgresql+asyncpg://"):
            errors.append("system_database_url must use postgresql+asyncpg")
        if self.config.get("system_database_schema_mode") != "validate":
            errors.append("system_database_schema_mode must be validate")
        if self.config.get("runtime_store_backend") != "postgresql":
            errors.append("runtime_store_backend must be postgresql")
        if not self.config.get("runtime_durable_queue_enabled"):
            errors.append("runtime_durable_queue_enabled must be true")
        if self.config.get("agent_workspace_writable"):
            errors.append("agent_workspace_writable must be false")
        if self.config.get("tool_state_backend") != "redis":
            errors.append("tool_state_backend must be redis")
        if self.config.get("audit_backend") != "postgresql":
            errors.append("audit_backend must be postgresql")
        if self.config.get("quota_backend") != "redis":
            errors.append("quota_backend must be redis")
        if self.config.get("security_rate_limit_backend") != "redis":
            errors.append("security_rate_limit_backend must be redis")
        if self.config.get("vault_enabled"):
            if not self.config.get("vault_address"):
                errors.append("vault_address is required")
            if not os.getenv(str(self.config.get("vault_token_env", "VAULT_TOKEN"))):
                errors.append("vault_token_env is not available")
        if self.config.get("workflow_backend") != "postgresql":
            errors.append("workflow_backend must be postgresql")
        if self.config.get("memory_backend") not in {
            "postgresql",
            "redis",
        }:
            errors.append("memory_backend must be postgresql or redis")
        # 禁止通配CORS，并要求前端Origin使用HTTPS，降低浏览器侧凭证泄露风险。
        origins = self.config.get("system_frontend_origins", [])
        if not origins or any(
            origin == "*" or not str(origin).startswith("https://")
            for origin in origins
        ):
            errors.append("system_frontend_origins must contain explicit HTTPS origins")
        if self.config.get("system_jwt_secret"):
            errors.append("system_jwt_secret must use system_jwt_secret_env")
        if self.config.get("system_initial_admin_password"):
            errors.append(
                "system_initial_admin_password must use "
                "system_initial_admin_password_env"
            )
        if self.config.get("security_jwt_secret"):
            errors.append("security_jwt_secret must use security_jwt_secret_env")
        # 生产模型密钥必须通过api_key_env引用，不允许直接写入YAML或数据库配置。
        plaintext_models = [
            str(item.get("name", "unnamed"))
            for item in self.config.get("models", [])
            if isinstance(item, dict) and item.get("api_key")
        ]
        if plaintext_models:
            errors.append(
                "model api_key must use api_key_env in production: "
                + ", ".join(plaintext_models)
            )
        # 在第一个外部连接建立前终止启动，避免服务带着部分危险配置上线。
        if errors:
            raise ValueError("Unsafe production configuration: " + "; ".join(errors))

    def run(self) -> None:
        """
        组装平台并启动Uvicorn。
        """
        # 先完成全部依赖组装；任何配置或资源错误都会在监听端口前暴露。
        application = self.build()
        # 仅run负责启动HTTP服务器，测试可直接调用build获取Application。
        self._start_server(application)

    def _load_config(self) -> None:
        """
        加载并校验当前运行环境的完整配置。

        加载顺序：
        1. 定位环境选择文件config.yaml；
        2. 从显式参数、环境变量或选择文件中确定environment；
        3. 只读取config.<environment>.yaml；
        4. 使用Bootstrap显式参数覆盖环境文件；
        5. 使用BootstrapConfig完成强类型校验。
        """
        # bootstrap.py位于app/bootstrap目录，因此向上两级得到项目根目录。
        project_root = Path(__file__).resolve().parents[2]

        # config_file只表示“环境选择文件”，默认是项目根目录的config.yaml。
        # 调用方显式传入的路径优先级最高，其次是EAP_CONFIG_FILE环境变量。
        config_file = self.config.get(
            "config_file",
            os.getenv("EAP_CONFIG_FILE", str(project_root / "config.yaml")),
        )

        # 选择文件只用于取得environment，不作为业务配置参与后续合并。
        selector_config = self._load_yaml_config(config_file)

        # 环境选择优先级：
        # Bootstrap({"environment": ...}) > EAP_ENVIRONMENT > config.yaml > test。
        environment = self.config.get(
            "environment",
            os.getenv(
                "EAP_ENVIRONMENT",
                selector_config.get("environment", "test"),
            ),
        )

        # 当前平台只允许测试和生产两种明确环境，防止拼写错误加载错误文件。
        if environment not in {"test", "production"}:
            raise ValueError("Invalid environment; expected 'test' or 'production'")

        # 环境文件与选择文件位于同一目录，并继承选择文件的扩展名。
        # 例如config.yaml + test会得到config.test.yaml。
        config_path = Path(config_file) if config_file else project_root / "config.yaml"
        environment_file = config_path.with_name(
            f"{config_path.stem}.{environment}{config_path.suffix}"
        )

        # 只加载当前环境文件，不读取或合并另一套环境配置。
        file_config = self._load_yaml_config(str(environment_file))

        # 环境文件必须存在且包含YAML映射，避免使用默认值意外启动服务。
        if not file_config:
            raise FileNotFoundError(
                f"Environment config file not found or empty: {environment_file}"
            )

        # environment以最终选择结果为准，防止环境文件内部写入相反的值。
        file_config["environment"] = environment

        # 这些值是平台兜底值，也允许通过环境变量覆盖。
        # 环境文件将在下一步覆盖同名兜底值。
        defaults = {
            # HTTP服务监听地址。
            "host": os.getenv("EAP_HOST", "0.0.0.0"),
            # 环境变量是字符串，这里先转换为整数再交给Pydantic校验范围。
            "port": int(os.getenv("EAP_PORT", "8000")),
            # 平台日志等级。
            "log_level": os.getenv("EAP_LOG_LEVEL", "INFO"),
            # 兼容旧版单模型配置；多模型场景优先使用models。
            "api_key": self.secret_manager.get("EAP_OPENAI_API_KEY"),
            "base_url": os.getenv("EAP_OPENAI_BASE_URL"),
            "model": os.getenv("EAP_MODEL"),
            # API请求未指定Agent时使用的默认Agent名称。
            "default_agent": os.getenv("EAP_DEFAULT_AGENT", "default"),
        }

        # 当前环境文件覆盖平台兜底值。
        defaults.update(file_config)

        # Database credentials are deployment secrets. A process-level URL
        # overrides the checked-in template, matching Alembic and allowing
        # CI or containers to inject their own database endpoint.
        environment_database_url = os.getenv("EAP_SYSTEM_DATABASE_URL")
        if environment_database_url:
            defaults["system_database_url"] = environment_database_url

        # 构造Bootstrap时显式传入的参数拥有最高优先级。
        # prompts/tools/agents等Python对象也在这里进入最终配置。
        defaults.update(self.config)

        # 所有普通配置统一经过Pydantic校验，未知字段和非法范围会立即报错。
        try:
            validated = BootstrapConfig.model_validate(defaults)
        except Exception as error:
            raise ValueError(f"Invalid Bootstrap configuration: {error}") from error

        # Bootstrap其余组装代码仍使用字典访问，因此将强类型模型转回字典。
        # exclude_none=False保留None，以便后续逻辑区分“未配置”和“字段不存在”。
        self.config = validated.model_dump(exclude_none=False)

        # 以下列表可能包含实际Python对象，不能使用Pydantic序列化后的副本。
        # 因此从校验前的defaults中恢复原始引用。
        for key in (
            "prompts",
            "tools",
            "agents",
            "llm_agents",
            "llm_provider_factories",
        ):
            if key in defaults:
                self.config[key] = defaults[key]

        # llm_agents支持两种来源：
        # 1. 代码直接传入AgentConfig；
        # 2. YAML填写普通字典。
        # 这里统一转换成AgentConfig，后续注册流程无需区分来源。
        self.config["llm_agents"] = [
            item if isinstance(item, AgentConfig) else AgentConfig(**item)
            for item in self.config.get("llm_agents", [])
        ]

    @staticmethod
    def _load_yaml_config(config_file: str | None) -> dict[str, Any]:
        """
        安全读取单个YAML配置文件。

        返回普通字典；文件不存在或路径为空时返回空字典，由调用方决定
        该文件是可选文件还是必须文件。
        """
        # Path可能为空，并且选择文件允许通过调用方进行缺失处理。
        if not config_file or not os.path.exists(config_file):
            return {}

        # 明确使用UTF-8读取，保证中文注释和字符串跨平台一致。
        with open(config_file, encoding="utf-8") as file:
            # safe_load只解析YAML基础类型，不实例化任意Python对象。
            # 空文件会得到None，因此使用or {}统一为空字典。
            config = yaml.safe_load(file) or {}

        # 平台顶层配置必须是键值映射，禁止使用列表或标量作为根节点。
        if not isinstance(config, dict):
            raise TypeError(f"Config file must contain a mapping: {config_file}")

        # 返回原始映射，字段类型和未知字段由BootstrapConfig统一校验。
        return config

    @staticmethod
    def _merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        """递归合并配置，便于local文件只覆盖单个模型。"""
        # 复制基础字典，避免合并过程意外修改调用方持有的原配置。
        result = dict(base)

        # 映射类型递归合并；标量、列表和对象由高优先级配置整体替换。
        for key, value in override.items():
            if isinstance(result.get(key), dict) and isinstance(value, dict):
                result[key] = BootstrapConfigurationMixin._merge_config(
                    result[key], value
                )
            else:
                result[key] = value

        return result

    def _init_logger(self) -> None:
        """根据平台配置初始化Python根日志格式和等级。"""
        # getattr将字符串等级转换为logging常量，非法值安全回退到INFO。
        configure_logging(
            level=getattr(logging, str(self.config["log_level"]).upper(), logging.INFO),
            json_enabled=self.config.get("log_format") == "json",
        )
