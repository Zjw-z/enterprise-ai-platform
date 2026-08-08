"""Vector storage contracts shared by Memory and Knowledge domains."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class VectorRecord:
    id: str
    vector: list[float]
    tenant_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VectorMatch:
    id: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseVectorStore(ABC):
    @abstractmethod
    async def initialize(self) -> None: ...

    @abstractmethod
    async def upsert(
        self, collection: str, records: list[VectorRecord]
    ) -> None: ...

    @abstractmethod
    async def search(
        self,
        collection: str,
        vector: list[float],
        *,
        tenant_id: str,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorMatch]: ...

    @abstractmethod
    async def delete(
        self,
        collection: str,
        ids: list[str],
        *,
        tenant_id: str,
    ) -> None: ...

    @abstractmethod
    async def health_check(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...
