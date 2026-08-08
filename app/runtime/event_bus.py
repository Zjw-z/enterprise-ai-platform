"""兼容入口：EventBus基础设施已下沉到core.observability。"""

from app.core.observability import EventBus, EventHandler

__all__ = ["EventBus", "EventHandler"]
