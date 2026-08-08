"""Bootstrap 基础设施 Adapter 构造逻辑。"""

from pathlib import Path

from app.core.quota import RedisTenantQuotaManager, TenantQuota, TenantQuotaManager
from app.core.security import Principal, RedisRateLimiter, SecurityManager
from app.memory import (
    BaseMemoryStore,
    InMemoryStore,
    PostgreSQLMemoryStore,
    RedisMemoryStore,
    SQLiteMemoryStore,
)
from app.system import SystemDatabase, SystemManagementService, SystemTokenService
from app.vector import BaseVectorStore, MilvusCollectionSpec, MilvusVectorStore


class BootstrapInfrastructureMixin:
    """构造数据库、记忆、向量、安全与配额 Adapter。"""

    def _create_memory_store(self) -> BaseMemoryStore:
        """根据环境配置创建唯一MemoryStore。"""
        # backend决定具体Adapter，MemoryManager始终使用同一个BaseMemoryStore接口。
        backend = self.config.get(
            "memory_backend",
            "in_memory",
        )
        # 内存实现适合单元测试，进程退出后数据即消失。
        if backend == "in_memory":
            return InMemoryStore()
        # SQLite适合单机学习环境，不作为集群生产Memory后端。
        if backend == "sqlite":
            configured = str(
                self.config.get(
                    "memory_sqlite_path",
                    "data/memory.db",
                )
            )
            path = Path(configured)
            if not path.is_absolute():
                project_root = (
                    Path(__file__).resolve().parents[2]
                )
                path = project_root / path
            return SQLiteMemoryStore(str(path))
        # Redis适合高频会话数据；连接串通过SecretManager解析。
        if backend == "redis":
            url = self.secret_manager.resolve(
                direct_value=self.config.get(
                    "memory_redis_url"
                ),
                secret_name=self.config.get(
                    "memory_redis_url_env"
                ),
            )
            if not url:
                raise ValueError(
                    "Redis memory requires memory_redis_url "
                    "or memory_redis_url_env."
                )
            return RedisMemoryStore(url=str(url))
        # PostgreSQL适合需要事务、审计和可靠持久化的企业部署。
        if backend == "postgresql":
            dsn = self.secret_manager.resolve(
                direct_value=self.config.get(
                    "memory_postgresql_dsn"
                ),
                secret_name=self.config.get(
                    "memory_postgresql_dsn_env"
                ),
            )
            if not dsn:
                raise ValueError(
                    "PostgreSQL memory requires "
                    "memory_postgresql_dsn or "
                    "memory_postgresql_dsn_env."
                )
            return PostgreSQLMemoryStore(dsn=str(dsn))
        raise ValueError(
            f"Unsupported memory backend: {backend}"
        )

    def _create_vector_store(
        self,
    ) -> BaseVectorStore | None:
        """创建供知识库和语义记忆共享的Milvus向量存储。"""
        # none明确表示关闭向量能力，上层据此禁用相关功能而不是伪造结果。
        backend = self.config.get("vector_store_backend", "none")
        if backend == "none":
            return None
        if backend != "milvus":
            raise ValueError(
                f"Unsupported vector store backend: {backend}"
            )
        # 无认证Milvus允许token为空，生产集群可通过环境变量提供认证Token。
        token = self.secret_manager.resolve(
            direct_value=self.config.get("milvus_token"),
            secret_name=self.config.get("milvus_token_env"),
        )
        dimension = int(
            self.config.get("milvus_embedding_dimensions", 1024)
        )
        # 同一Milvus连接建立记忆和知识两个独立Collection，避免业务语义混杂。
        return MilvusVectorStore(
            uri=(
                f"http://{self.config.get('milvus_host', 'localhost')}:"
                f"{self.config.get('milvus_port', 19530)}"
            ),
            database=str(
                self.config.get("milvus_database", "enterprise_ai")
            ),
            token=str(token) if token else None,
            auto_create=bool(
                self.config.get("milvus_auto_create", True)
            ),
            collections=[
                MilvusCollectionSpec(
                    str(
                        self.config.get(
                            "milvus_memory_collection",
                            "agent_memory_vectors",
                        )
                    ),
                    dimension,
                ),
                MilvusCollectionSpec(
                    str(
                        self.config.get(
                            "milvus_knowledge_collection",
                            "knowledge_vectors",
                        )
                    ),
                    dimension,
                ),
            ],
            metric_type=str(
                self.config.get("milvus_metric_type", "COSINE")
            ),
            index_type=str(
                self.config.get("milvus_index_type", "HNSW")
            ),
            index_m=int(self.config.get("milvus_index_m", 16)),
            index_ef_construction=int(
                self.config.get(
                    "milvus_index_ef_construction", 200
                )
            ),
            search_ef=int(
                self.config.get("milvus_search_ef", 64)
            ),
            connect_attempts=int(
                self.config.get("milvus_connect_attempts", 12)
            ),
            connect_backoff_seconds=float(
                self.config.get(
                    "milvus_connect_backoff_seconds", 2.0
                )
            ),
            delete_verify_attempts=int(
                self.config.get(
                    "milvus_delete_verify_attempts", 20
                )
            ),
            delete_verify_backoff_seconds=float(
                self.config.get(
                    "milvus_delete_verify_backoff_seconds", 0.1
                )
            ),
        )

    def _create_security_manager(self) -> SecurityManager:
        """解析API Key来源并创建可信主体认证服务。"""
        # security_enabled控制业务执行入口认证，系统管理JWT仍可独立启用。
        enabled = bool(
            self.config.get("security_enabled", False)
        )
        jwt_secret = self.config.get(
            "security_jwt_secret"
        )
        jwt_secret_env = self.config.get(
            "security_jwt_secret_env"
        )
        jwt_secret = self.secret_manager.resolve(
            direct_value=jwt_secret,
            secret_name=(
                str(jwt_secret_env)
                if jwt_secret_env
                else None
            ),
        )
        if not jwt_secret and self.config.get(
            "system_management_enabled",
            True,
        ):
            jwt_secret = self.secret_manager.resolve(
                direct_value=self.config.get(
                    "system_jwt_secret"
                ),
                secret_name=self.config.get(
                    "system_jwt_secret_env"
                ),
            )
        # API Key只以摘要作为字典键保存，避免运行内存长期保留明文索引。
        credentials: dict[str, Principal] = {}
        for principal_id, raw in self.config.get(
            "api_principals",
            {},
        ).items():
            api_key = raw.get("api_key")
            api_key_env = raw.get("api_key_env")
            api_key = self.secret_manager.resolve(
                direct_value=api_key,
                secret_name=(
                    str(api_key_env)
                    if api_key_env
                    else None
                ),
            )
            if not api_key:
                if enabled and not jwt_secret:
                    raise ValueError(
                        f"API principal '{principal_id}' has no "
                        "available api_key or api_key_env value."
                    )
                continue
            # Principal携带租户、用户、角色及Agent/Tool/Model授权范围。
            principal = Principal(
                principal_id=str(principal_id),
                tenant_id=str(raw["tenant_id"]),
                user_id=str(raw["user_id"]),
                roles=frozenset(raw.get("roles", [])),
                permissions=frozenset(raw.get("permissions", [])),
                allowed_agents=frozenset(
                    raw.get("allowed_agents", ["*"])
                ),
                allowed_tools=frozenset(
                    raw.get("allowed_tools", ["*"])
                ),
                allowed_models=frozenset(
                    raw.get("allowed_models", ["*"])
                ),
                requests_per_minute=raw.get(
                    "requests_per_minute"
                ),
            )
            credentials[
                SecurityManager.digest(str(api_key))
            ] = principal
        return SecurityManager(
            enabled=enabled,
            credentials=credentials,
            jwt_secret=jwt_secret,
            jwt_issuer=self.config.get(
                "security_jwt_issuer"
            ),
            jwt_audience=self.config.get(
                "security_jwt_audience"
            ),
            default_requests_per_minute=self.config.get(
                "security_default_requests_per_minute"
            ),
            authorization_policies=list(
                self.config.get(
                    "authorization_policies",
                    [],
                )
            ),
            distributed_rate_limiter=(
                RedisRateLimiter(self._resolve_quota_redis_url())
                if self.config.get(
                    "security_rate_limit_backend", "in_memory"
                )
                == "redis"
                else None
            ),
        )

    def _create_system_management_service(
        self,
    ) -> SystemManagementService:
        """创建PostgreSQL系统管理、Token签发和初始管理员模块。"""
        # JWT签名密钥和初始密码优先从环境变量引用解析。
        secret = self.secret_manager.resolve(
            direct_value=self.config.get(
                "system_jwt_secret"
            ),
            secret_name=self.config.get(
                "system_jwt_secret_env"
            ),
        )
        password = self.secret_manager.resolve(
            direct_value=self.config.get(
                "system_initial_admin_password"
            ),
            secret_name=self.config.get(
                "system_initial_admin_password_env"
            ),
        )
        if not secret:
            raise ValueError(
                "System management requires system_jwt_secret "
                "or system_jwt_secret_env."
            )
        if not password:
            raise ValueError(
                "System management requires an initial admin "
                "password or password environment variable."
            )
        # SystemDatabase集中管理异步Engine、连接池、Session和Schema模式。
        database = SystemDatabase(
            str(self.config["system_database_url"]),
            schema_mode=str(
                self.config.get(
                    "system_database_schema_mode",
                    "create_all",
                )
            ),
            pool_size=int(
                self.config.get(
                    "system_database_pool_size",
                    10,
                )
            ),
            max_overflow=int(
                self.config.get(
                    "system_database_max_overflow",
                    20,
                )
            ),
            pool_timeout_seconds=float(
                self.config.get(
                    "system_database_pool_timeout_seconds",
                    30.0,
                )
            ),
        )
        # Service在应用生命周期启动时初始化Schema并确保初始管理员存在。
        return SystemManagementService(
            database,
            SystemTokenService(
                str(secret),
                access_ttl_seconds=int(
                    self.config[
                        "system_access_token_ttl_seconds"
                    ]
                ),
                refresh_ttl_seconds=int(
                    self.config[
                        "system_refresh_token_ttl_seconds"
                    ]
                ),
            ),
            initial_admin_username=str(
                self.config[
                    "system_initial_admin_username"
                ]
            ),
            initial_admin_password=str(password),
            initial_tenant_id=str(
                self.config["system_initial_tenant_id"]
            ),
        )

    def _create_quota_manager(self) -> TenantQuotaManager:
        """创建默认配额及租户覆盖配置。"""
        # 所有租户先继承默认值，再由tenant_quotas进行定向覆盖。
        raw_default = self.config.get(
            "default_tenant_quota",
            {},
        )
        default = TenantQuota(
            max_concurrent_tasks=int(
                raw_default.get(
                    "max_concurrent_tasks",
                    10,
                )
            ),
            max_requests_per_day=int(
                raw_default.get(
                    "max_requests_per_day",
                    10_000,
                )
            ),
        )
        quotas = {
            str(tenant_id): TenantQuota(
                max_concurrent_tasks=int(
                    raw.get(
                        "max_concurrent_tasks",
                        default.max_concurrent_tasks,
                    )
                ),
                max_requests_per_day=int(
                    raw.get(
                        "max_requests_per_day",
                        default.max_requests_per_day,
                    )
                ),
            )
            for tenant_id, raw in self.config.get(
                "tenant_quotas",
                {},
            ).items()
        }
        if self.config.get("quota_backend", "in_memory") == "redis":
            return RedisTenantQuotaManager(
                redis_url=self._resolve_quota_redis_url(),
                default_quota=default,
                quotas=quotas,
                active_ttl_seconds=int(
                    self.config.get("quota_active_ttl_seconds", 600)
                ),
            )
        return TenantQuotaManager(
            default_quota=default,
            quotas=quotas,
        )

    def _resolve_quota_redis_url(self) -> str:
        """统一解析分布式限流和配额共享的Redis连接地址。"""
        redis_url = self.secret_manager.resolve(
            direct_value=self.config.get("quota_redis_url"),
            secret_name=self.config.get("quota_redis_url_env"),
        )
        if redis_url:
            return str(redis_url)
        from urllib.parse import quote

        password = self.config.get("redis_password")
        credentials = (
            f":{quote(str(password), safe='')}@"
            if password
            else ""
        )
        return (
            f"redis://{credentials}"
            f"{self.config.get('redis_host', 'localhost')}:"
            f"{self.config.get('redis_port', 6379)}/"
            f"{self.config.get('redis_database', 0)}"
        )
