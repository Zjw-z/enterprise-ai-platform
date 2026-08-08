"""兼容入口：Trace基础设施已下沉到core.observability。"""

from app.core.observability import Span, Trace, TraceManager

__all__ = ["Span", "Trace", "TraceManager"]
