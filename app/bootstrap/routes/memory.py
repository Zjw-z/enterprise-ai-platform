"""memory 路由。"""

from app.bootstrap.routes.common import *  # noqa: F403


def register_memory_routes(application) -> None:
    """向应用注册本业务域路由。"""

    self = application
    @self.fastapi.get("/v1/memory/{agent_name}")
    async def list_user_memory(
        agent_name: str,
        request: Request,
        limit: int = 100,
        offset: int = 0,
        tenant_id: str = "default",
        user_id: str = "anonymous",
    ) -> list[dict[str, Any]]:
        principal = self._authenticate(request)
        self._authorize_agent(principal, agent_name)
        namespace = self.memory_manager.build_namespace(
            tenant_id=(
                principal.tenant_id
                if principal
                else tenant_id
            ),
            user_id=(
                principal.user_id
                if principal
                else user_id
            ),
            agent_id=agent_name,
        )
        return [
            asdict(item)
            for item in await self.memory_manager.list_long_term(
                namespace,
                min(max(limit, 1), 200),
                max(offset, 0),
            )
        ]

    @self.fastapi.put(
        "/v1/memory/{agent_name}/{memory_key}"
    )
    async def upsert_user_memory(
        agent_name: str,
        memory_key: str,
        payload: MemoryUpsertRequest,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._authorize_agent(principal, agent_name)
        namespace = self.memory_manager.build_namespace(
            tenant_id=(
                principal.tenant_id
                if principal
                else payload.tenant_id
            ),
            user_id=(
                principal.user_id
                if principal
                else payload.user_id
            ),
            agent_id=agent_name,
        )
        action = await self.memory_manager.remember(
            memory_key,
            payload.content,
            payload.memory_type,
            namespace,
            confidence=payload.confidence,
            source=payload.source,
            metadata=payload.metadata,
        )
        item = await self.memory_manager.get_long_term(
            memory_key,
            namespace,
        )
        return {
            "action": action,
            "memory": asdict(item) if item else None,
        }

    @self.fastapi.get(
        "/v1/memory/{agent_name}/sessions"
    )
    async def list_memory_sessions(
        agent_name: str,
        request: Request,
        limit: int = 50,
        offset: int = 0,
        tenant_id: str = "default",
        user_id: str = "anonymous",
    ) -> list[dict[str, Any]]:
        principal = self._authenticate(request)
        self._authorize_agent(principal, agent_name)
        namespace = self.memory_manager.build_namespace(
            tenant_id=(
                principal.tenant_id
                if principal
                else tenant_id
            ),
            user_id=(
                principal.user_id
                if principal
                else user_id
            ),
            agent_id=agent_name,
        )
        sessions = await self.memory_manager.list_sessions(
            namespace,
            min(max(limit, 1), 200),
            max(offset, 0),
        )
        return [
            {
                "session_id": item.session_id,
                "summary": item.summary,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
                "metadata": item.metadata,
            }
            for item in sessions
        ]

    @self.fastapi.get(
        "/v1/memory/{agent_name}/sessions/{session_id}"
    )
    async def get_memory_session(
        agent_name: str,
        session_id: str,
        request: Request,
        limit: int = 500,
        tenant_id: str = "default",
        user_id: str = "anonymous",
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._authorize_agent(principal, agent_name)
        namespace = self.memory_manager.build_namespace(
            tenant_id=(
                principal.tenant_id
                if principal
                else tenant_id
            ),
            user_id=(
                principal.user_id
                if principal
                else user_id
            ),
            agent_id=agent_name,
        )
        conversation = (
            await self.memory_manager.get_conversation(
                session_id,
                namespace,
            )
        )
        messages = (
            await self.memory_manager.get_session_messages(
                session_id,
                namespace,
                min(max(limit, 1), 2000),
            )
        )
        if conversation is None and not messages:
            raise HTTPException(
                status_code=404,
                detail="Memory session not found.",
            )
        return {
            "session_id": session_id,
            "summary": (
                conversation.summary
                if conversation
                else None
            ),
            "metadata": (
                conversation.metadata
                if conversation
                else {}
            ),
            "messages": [
                asdict(item) for item in messages
            ],
        }

    @self.fastapi.delete(
        "/v1/memory/{agent_name}/{memory_key}"
    )
    async def delete_user_memory(
        agent_name: str,
        memory_key: str,
        request: Request,
        tenant_id: str = "default",
        user_id: str = "anonymous",
    ) -> dict[str, bool]:
        principal = self._authenticate(request)
        self._authorize_agent(principal, agent_name)
        namespace = self.memory_manager.build_namespace(
            tenant_id=(
                principal.tenant_id
                if principal
                else tenant_id
            ),
            user_id=(
                principal.user_id
                if principal
                else user_id
            ),
            agent_id=agent_name,
        )
        await self.memory_manager.forget(
            memory_key,
            namespace,
        )
        return {"deleted": True}
