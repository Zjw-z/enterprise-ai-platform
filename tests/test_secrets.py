"""SecretManager Provider优先级测试。"""

from app.core.secrets import (
    BaseSecretProvider,
    CachedSecretProvider,
    MountedFileSecretProvider,
    SecretManager,
)


class DictSecretProvider(BaseSecretProvider):
    """使用字典模拟Vault或KMS。"""

    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    def get(self, name: str) -> str | None:
        return self.values.get(name)


def test_secret_manager_uses_direct_value_first() -> None:
    """直接配置非空时不查询外部Provider。"""
    manager = SecretManager(
        [DictSecretProvider({"MODEL_KEY": "provider"})]
    )
    assert manager.resolve(
        direct_value="direct",
        secret_name="MODEL_KEY",
    ) == "direct"


def test_secret_manager_falls_back_across_providers() -> None:
    """SecretManager应按Provider注册顺序查找。"""
    manager = SecretManager(
        [
            DictSecretProvider({}),
            DictSecretProvider({"MODEL_KEY": "vault-value"}),
        ]
    )
    assert manager.get("MODEL_KEY") == "vault-value"
    assert manager.get("MISSING") is None


def test_mounted_secret_provider_blocks_path_escape(tmp_path) -> None:
    (tmp_path / "MODEL_KEY").write_text(
        "mounted-value\n", encoding="utf-8"
    )
    provider = MountedFileSecretProvider(tmp_path)

    assert provider.get("MODEL_KEY") == "mounted-value"
    assert provider.get("../outside") is None


def test_cached_secret_provider_avoids_repeated_external_reads() -> None:
    provider = DictSecretProvider({"MODEL_KEY": "first"})
    cached = CachedSecretProvider(provider, ttl_seconds=60)

    assert cached.get("MODEL_KEY") == "first"
    provider.values["MODEL_KEY"] = "second"
    assert cached.get("MODEL_KEY") == "first"
