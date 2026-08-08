"""A2A统一出口。"""

from .client import (
    A2AClient,
    A2AClientError,
    A2AClientManager,
)
from .registry import A2AAgentRegistry
from .remote_agent import RemoteA2AAgent
from .schema import (
    A2ATask,
    AgentCard,
    AgentInterface,
    AgentSkill,
)

__all__ = [
    "A2AClient",
    "A2AClientError",
    "A2AClientManager",
    "A2AAgentRegistry",
    "RemoteA2AAgent",
    "A2ATask",
    "AgentCard",
    "AgentInterface",
    "AgentSkill",
]
