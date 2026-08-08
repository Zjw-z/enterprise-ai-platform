"""Secret Provider扩展接口与统一解析服务。"""

import os
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path

import httpx


class BaseSecretProvider(ABC):
    """外部密钥系统必须实现的最小读取接口。"""

    @abstractmethod
    def get(self, name: str) -> str | None:
        """按逻辑名称读取Secret。"""


class EnvironmentSecretProvider(BaseSecretProvider):
    """从进程环境变量读取Secret。"""

    def get(self, name: str) -> str | None:
        return os.getenv(name)


class MountedFileSecretProvider(BaseSecretProvider):
    """读取Kubernetes Secret或Docker Secret挂载目录中的文件。"""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory).resolve()

    def get(self, name: str) -> str | None:
        candidate = (self.directory / name).resolve()
        if self.directory not in candidate.parents:
            return None
        try:
            value = candidate.read_text(encoding="utf-8").strip()
        except (FileNotFoundError, IsADirectoryError, PermissionError):
            return None
        return value or None


class VaultKV2SecretProvider(BaseSecretProvider):
    """从HashiCorp Vault KV v2读取名为value的密钥字段。"""

    def __init__(
        self,
        *,
        address: str,
        token: str,
        mount: str = "secret",
        path_prefix: str = "enterprise-ai",
        namespace: str | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.address = address.rstrip("/")
        self.token = token
        self.mount = mount.strip("/")
        self.path_prefix = path_prefix.strip("/")
        self.namespace = namespace
        self.timeout_seconds = timeout_seconds

    def get(self, name: str) -> str | None:
        path = "/".join(
            item
            for item in (self.path_prefix, name.strip("/"))
            if item
        )
        headers = {"X-Vault-Token": self.token}
        if self.namespace:
            headers["X-Vault-Namespace"] = self.namespace
        try:
            response = httpx.get(
                f"{self.address}/v1/{self.mount}/data/{path}",
                headers=headers,
                timeout=self.timeout_seconds,
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            data = response.json().get("data", {}).get("data", {})
            value = data.get("value")
            return str(value) if value is not None else None
        except (httpx.HTTPError, ValueError, TypeError):
            return None


class CachedSecretProvider(BaseSecretProvider):
    """为外部Provider增加有界TTL缓存，避免每次模型调用访问密钥系统。"""

    def __init__(
        self,
        provider: BaseSecretProvider,
        *,
        ttl_seconds: float = 60.0,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("Secret cache TTL must be positive.")
        self.provider = provider
        self.ttl_seconds = ttl_seconds
        self._cache: dict[str, tuple[float, str | None]] = {}
        self._lock = threading.Lock()

    def get(self, name: str) -> str | None:
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(name)
            if cached is not None and cached[0] > now:
                return cached[1]
        value = self.provider.get(name)
        with self._lock:
            self._cache[name] = (
                now + self.ttl_seconds,
                value,
            )
        return value


class SecretManager:
    """按Provider顺序解析Secret，不记录或输出Secret值。"""

    def __init__(
        self,
        providers: list[BaseSecretProvider],
    ) -> None:
        if not providers:
            raise ValueError(
                "SecretManager requires at least one provider."
            )
        self.providers = list(providers)

    def get(self, name: str | None) -> str | None:
        if not name:
            return None
        for provider in self.providers:
            value = provider.get(name)
            if value:
                return value
        return None

    def resolve(
        self,
        *,
        direct_value: str | None,
        secret_name: str | None,
    ) -> str | None:
        """直接配置优先，否则依次查询外部Provider。"""
        if direct_value:
            return direct_value
        return self.get(secret_name)
