"""Password hashing and signed token utilities."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(
        value + "=" * (-len(value) % 4)
    )


class PasswordHasher:
    algorithm = "pbkdf2_sha256"
    iterations = 600_000

    def hash(self, password: str) -> str:
        if len(password) < 8:
            raise ValueError(
                "Password must contain at least 8 characters."
            )
        salt = os.urandom(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode(),
            salt,
            self.iterations,
        )
        return "$".join(
            (
                self.algorithm,
                str(self.iterations),
                _encode(salt),
                _encode(digest),
            )
        )

    def verify(self, password: str, encoded: str) -> bool:
        try:
            algorithm, iterations, salt, expected = (
                encoded.split("$")
            )
            if algorithm != self.algorithm:
                return False
            digest = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode(),
                _decode(salt),
                int(iterations),
            )
            return hmac.compare_digest(
                digest,
                _decode(expected),
            )
        except (ValueError, TypeError):
            return False


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int


class SystemTokenService:
    def __init__(
        self,
        secret: str,
        *,
        issuer: str = "enterprise-ai-platform",
        access_ttl_seconds: int = 1800,
        refresh_ttl_seconds: int = 604_800,
    ) -> None:
        if len(secret) < 32:
            raise ValueError(
                "System JWT secret must be at least 32 characters."
            )
        self.secret = secret.encode()
        self.issuer = issuer
        self.access_ttl_seconds = access_ttl_seconds
        self.refresh_ttl_seconds = refresh_ttl_seconds

    def issue_pair(
        self,
        *,
        user_id: str,
        tenant_id: str,
        username: str,
        roles: list[str],
        permissions: list[str],
    ) -> tuple[TokenPair, str, int]:
        now = int(time.time())
        refresh_id = str(uuid.uuid4())
        common = {
            "sub": user_id,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "username": username,
            "roles": roles,
            "permissions": permissions,
            "iss": self.issuer,
            "iat": now,
        }
        access = self._encode_token(
            {
                **common,
                "typ": "access",
                "exp": now + self.access_ttl_seconds,
            }
        )
        refresh = self._encode_token(
            {
                **common,
                "typ": "refresh",
                "jti": refresh_id,
                "exp": now + self.refresh_ttl_seconds,
            }
        )
        return (
            TokenPair(
                access_token=access,
                refresh_token=refresh,
                expires_in=self.access_ttl_seconds,
            ),
            refresh_id,
            now + self.refresh_ttl_seconds,
        )

    def decode(
        self,
        token: str,
        *,
        expected_type: str,
    ) -> dict[str, Any]:
        try:
            encoded_header, encoded_payload, signature = (
                token.split(".")
            )
            signing_input = (
                f"{encoded_header}.{encoded_payload}"
            ).encode()
            expected = hmac.new(
                self.secret,
                signing_input,
                hashlib.sha256,
            ).digest()
            if not hmac.compare_digest(
                expected,
                _decode(signature),
            ):
                raise ValueError("Invalid token signature.")
            payload = json.loads(
                _decode(encoded_payload)
            )
            if payload.get("iss") != self.issuer:
                raise ValueError("Invalid token issuer.")
            if payload.get("typ") != expected_type:
                raise ValueError("Invalid token type.")
            if int(payload.get("exp", 0)) <= int(time.time()):
                raise ValueError("Token expired.")
            return payload
        except (
            ValueError,
            TypeError,
            json.JSONDecodeError,
        ) as error:
            raise ValueError("Invalid token.") from error

    def token_hash(self, token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def _encode_token(self, payload: dict[str, Any]) -> str:
        header = _encode(
            json.dumps(
                {"alg": "HS256", "typ": "JWT"},
                separators=(",", ":"),
            ).encode()
        )
        body = _encode(
            json.dumps(
                payload,
                separators=(",", ":"),
            ).encode()
        )
        signature = _encode(
            hmac.new(
                self.secret,
                f"{header}.{body}".encode(),
                hashlib.sha256,
            ).digest()
        )
        return f"{header}.{body}.{signature}"
