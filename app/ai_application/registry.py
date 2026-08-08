"""线程安全的 AI 应用运行快照。"""

import threading

from .schema import AIApplicationDefinition


class AIApplicationRegistry:
    def __init__(self) -> None:
        self._items: dict[str, AIApplicationDefinition] = {}
        self._lock = threading.RLock()

    def replace_all(self, items: list[AIApplicationDefinition]) -> None:
        snapshot = {item.name: item for item in items}
        with self._lock:
            self._items = snapshot

    def get(self, name: str) -> AIApplicationDefinition | None:
        with self._lock:
            return self._items.get(name)

    def list(self, *, include_inactive: bool = True) -> list[AIApplicationDefinition]:
        with self._lock:
            values = list(self._items.values())
        if not include_inactive:
            values = [item for item in values if item.status == "published"]
        return sorted(values, key=lambda item: (item.menu.order, item.name))
