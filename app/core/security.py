"""平台认证主体与API Key授权服务。"""

import base64
import hashlib
import hmac
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class Principal:
    """经过认证的可信调用主体。"""

    principal_id: str
    tenant_id: str
    user_id: str
    roles: frozenset[str] = field(default_factory=frozenset)
    permissions: frozenset[str] = field(default_factory=frozenset)
    allowed_agents: frozenset[str] = field(
        default_factory=lambda: frozenset({"*"})
    )
    allowed_tools: frozenset[str] = field(
        default_factory=lambda: frozenset({"*"})
    )
    allowed_models: frozenset[str] = field(
        default_factory=lambda: frozenset({"*"})
    )
    requests_per_minute: int | None = None

    def can_access(
        self,
        resource: str,
        allowed: frozenset[str],
    ) -> bool:
        return "*" in allowed or resource in allowed


class AuthorizationPolicy(Protocol):
    """RBAC/ABAC policy extension contract."""

    def authorize(
        self,
        principal: Principal,
        *,
        action: str,
        resource_type: str,
        resource: str,
        context: dict[str, Any],
    ) -> bool | None:
        """Return False to deny, True to allow, None to abstain."""
        ...


class RedisRateLimiter:
    """使用Redis Lua对主体执行跨实例原子固定窗口限流。"""

    _SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then redis.call('EXPIRE', KEYS[1], ARGV[2]) end
local ttl = redis.call('TTL', KEYS[1])
if current > tonumber(ARGV[1]) then return {0, ttl} end
return {1, ttl}
"""

    def __init__(
        self,
        redis_url: str,
        *,
        key_prefix: str = "eap:rate",
    ) -> None:
        from redis.asyncio import from_url

        self.redis: Any = from_url(
            redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        self.key_prefix = key_prefix.rstrip(":")

    async def consume(
        self,
        principal_id: str,
        limit: int,
    ) -> tuple[bool, int]:
        window = int(time.time() // 60)
        key = f"{self.key_prefix}:{principal_id}:{window}"
        allowed, retry_after = await self.redis.eval(
            self._SCRIPT,
            1,
            key,
            limit,
            60,
        )
        return bool(int(allowed)), max(1, int(retry_after))

    async def close(self) -> None:
        await self.redis.aclose()

    async def health_check(self) -> None:
        """确认分布式限流 Redis 可用。"""

        if not await self.redis.ping():
            raise RuntimeError("Rate-limit Redis health check failed.")


class SecurityManager:
    """使用SHA-256摘要索引API Key并执行资源授权。"""

    def __init__(
        self,
        *,
        enabled: bool,
        credentials: dict[str, Principal] | None = None,
        jwt_secret: str | None = None,
        jwt_issuer: str | None = None,
        jwt_audience: str | None = None,
        default_requests_per_minute: int | None = None,
        authorization_policies: list[
            AuthorizationPolicy
        ] | None = None,
        distributed_rate_limiter: RedisRateLimiter | None = None,
    ) -> None:
        self.enabled = enabled
        self._credentials = dict(credentials or {})
        self._jwt_secret = jwt_secret
        self._jwt_issuer = jwt_issuer
        self._jwt_audience = jwt_audience
        self.default_requests_per_minute = (
            default_requests_per_minute
        )
        self.authorization_policies = list(
            authorization_policies or []
        )
        self.distributed_rate_limiter = distributed_rate_limiter
        self._buckets: dict[str, tuple[float, float]] = {}
        self._bucket_lock = threading.Lock()
        if (
            self.enabled
            and not self._credentials
            and not self._jwt_secret
        ):
            raise ValueError(
                "Security is enabled but no API Key or JWT "
                "credential source is configured."
            )

    @staticmethod
    def digest(api_key: str) -> str:
        """只保存Key摘要，避免认证服务长期持有明文索引。"""
        return hashlib.sha256(
            api_key.encode("utf-8")
        ).hexdigest()

    async def health_check(self) -> None:
        """检查安全模块依赖；本地模式没有外部健康项。"""

        if self.distributed_rate_limiter is not None:
            await self.distributed_rate_limiter.health_check()

    def authenticate(self, api_key: str) -> Principal | None:
        """认证API Key；比较摘要时使用恒定时间比较。"""
        if not self.enabled:
            return None
        candidate = self.digest(api_key)
        for digest, principal in self._credentials.items():
            if hmac.compare_digest(candidate, digest):
                return principal
        return None

    def authenticate_bearer(
        self,
        credential: str,
    ) -> Principal | None:
        """Bearer既支持平台API Key，也支持HS256 JWT。"""
        principal = self.authenticate(credential)
        if principal is not None:
            return principal
        if self._jwt_secret and credential.count(".") == 2:
            return self._authenticate_jwt(credential)
        return None

    def _authenticate_jwt(
        self,
        token: str,
    ) -> Principal | None:
        try:
            encoded_header, encoded_payload, encoded_signature = (
                token.split(".")
            )
            header = json.loads(
                self._decode_segment(encoded_header)
            )
            payload = json.loads(
                self._decode_segment(encoded_payload)
            )
            if header.get("alg") != "HS256":
                return None
            signing_input = (
                f"{encoded_header}.{encoded_payload}"
            ).encode("ascii")
            expected = hmac.new(
                self._jwt_secret.encode("utf-8"),
                signing_input,
                hashlib.sha256,
            ).digest()
            supplied = self._decode_bytes(
                encoded_signature
            )
            if not hmac.compare_digest(expected, supplied):
                return None

            now = time.time()
            if (
                payload.get("exp") is not None
                and float(payload["exp"]) <= now
            ):
                return None
            if (
                payload.get("nbf") is not None
                and float(payload["nbf"]) > now
            ):
                return None
            if (
                self._jwt_issuer
                and payload.get("iss") != self._jwt_issuer
            ):
                return None
            audience = payload.get("aud")
            if self._jwt_audience and not self._audience_matches(
                audience,
                self._jwt_audience,
            ):
                return None

            principal_id = str(payload.get("sub") or "")
            tenant_id = str(payload.get("tenant_id") or "")
            user_id = str(
                payload.get("user_id")
                or principal_id
            )
            if not principal_id or not tenant_id or not user_id:
                return None
            return Principal(
                principal_id=principal_id,
                tenant_id=tenant_id,
                user_id=user_id,
                roles=frozenset(payload.get("roles", [])),
                permissions=frozenset(payload.get("permissions", [])),
                allowed_agents=frozenset(
                    payload.get("allowed_agents", ["*"])
                ),
                allowed_tools=frozenset(
                    payload.get("allowed_tools", ["*"])
                ),
                allowed_models=frozenset(
                    payload.get("allowed_models", ["*"])
                ),
                requests_per_minute=(
                    int(payload["requests_per_minute"])
                    if payload.get(
                        "requests_per_minute"
                    ) is not None
                    else None
                ),
            )
        except (
            ValueError,
            TypeError,
            KeyError,
            json.JSONDecodeError,
        ):
            return None

    def check_rate_limit(
        self,
        principal: Principal,
    ) -> tuple[bool, int]:
        """消费一个令牌，并返回是否允许及建议重试秒数。"""
        limit = (
            principal.requests_per_minute
            or self.default_requests_per_minute
        )
        if limit is None:
            return True, 0
        if limit <= 0:
            return False, 60

        now = time.monotonic()
        refill_rate = limit / 60.0
        with self._bucket_lock:
            tokens, last = self._buckets.get(
                principal.principal_id,
                (float(limit), now),
            )
            tokens = min(
                float(limit),
                tokens + (now - last) * refill_rate,
            )
            if tokens < 1:
                retry_after = max(
                    1,
                    int((1 - tokens) / refill_rate) + 1,
                )
                self._buckets[
                    principal.principal_id
                ] = (tokens, now)
                return False, retry_after
            self._buckets[
                principal.principal_id
            ] = (tokens - 1, now)
        return True, 0

    async def check_distributed_rate_limit(
        self,
        principal: Principal,
    ) -> tuple[bool, int]:
        """生产使用Redis；没有Adapter时保留原进程内实现。"""
        limit = (
            principal.requests_per_minute
            or self.default_requests_per_minute
        )
        if limit is None:
            return True, 0
        if limit <= 0:
            return False, 60
        if self.distributed_rate_limiter is None:
            return self.check_rate_limit(principal)
        return await self.distributed_rate_limiter.consume(
            principal.principal_id,
            limit,
        )

    async def close(self) -> None:
        if self.distributed_rate_limiter is not None:
            await self.distributed_rate_limiter.close()

    @staticmethod
    def _decode_bytes(segment: str) -> bytes:
        padding = "=" * (-len(segment) % 4)
        return base64.urlsafe_b64decode(segment + padding)

    @classmethod
    def _decode_segment(cls, segment: str) -> str:
        return cls._decode_bytes(segment).decode("utf-8")

    @staticmethod
    def _audience_matches(
        actual: object,
        expected: str,
    ) -> bool:
        if isinstance(actual, str):
            return actual == expected
        if isinstance(actual, list):
            return expected in actual
        return False

    def authorize_agent(
        self,
        principal: Principal,
        agent_name: str,
        context: dict[str, Any] | None = None,
    ) -> bool:
        default = principal.can_access(
            agent_name,
            principal.allowed_agents,
        )
        return self._apply_policies(
            principal,
            action="execute",
            resource_type="agent",
            resource=agent_name,
            context=context,
            default=default,
        )

    def authorize_tool(
        self,
        principal: Principal,
        tool_name: str,
        context: dict[str, Any] | None = None,
    ) -> bool:
        default = principal.can_access(
            tool_name,
            principal.allowed_tools,
        )
        return self._apply_policies(
            principal,
            action="execute",
            resource_type="tool",
            resource=tool_name,
            context=context,
            default=default,
        )

    def authorize_model(
        self,
        principal: Principal,
        model_name: str,
        context: dict[str, Any] | None = None,
    ) -> bool:
        default = principal.can_access(
            model_name,
            principal.allowed_models,
        )
        return self._apply_policies(
            principal,
            action="invoke",
            resource_type="model",
            resource=model_name,
            context=context,
            default=default,
        )

    def authorize(
        self,
        principal: Principal,
        *,
        action: str,
        resource_type: str,
        resource: str,
        context: dict[str, Any] | None = None,
        default: bool = False,
    ) -> bool:
        return self._apply_policies(
            principal,
            action=action,
            resource_type=resource_type,
            resource=resource,
            context=context,
            default=default,
        )

    def _apply_policies(
        self,
        principal: Principal,
        *,
        action: str,
        resource_type: str,
        resource: str,
        context: dict[str, Any] | None,
        default: bool,
    ) -> bool:
        allowed = default
        for policy in self.authorization_policies:
            decision = policy.authorize(
                principal,
                action=action,
                resource_type=resource_type,
                resource=resource,
                context=dict(context or {}),
            )
            if decision is False:
                return False
            if decision is True:
                allowed = True
        return allowed
