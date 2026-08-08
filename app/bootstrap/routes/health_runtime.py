"""健康检查、Runtime 与任务追踪路由。"""

from app.bootstrap.routes.common import *  # noqa: F403


def register_health_runtime_routes(application) -> None:
    """注册健康检查、同步执行和异步任务路由。"""

    self = application
    if self.metrics is not None:

        async def prometheus_metrics() -> Response:
            return Response(
                content=self.metrics.render(),
                media_type=PlatformMetrics.CONTENT_TYPE,
            )

        self.fastapi.add_api_route(
            self.metrics_path,
            prometheus_metrics,
            methods=["GET"],
            include_in_schema=False,
        )

    @self.fastapi.get("/health")
    async def health(request: Request) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(principal, "platform_admin")
        return {
            "status": "ok",
            "agents": self.agent_registry.list_agents(),
            "models": self.llm_manager.list_models(),
            "model_health": self.llm_manager.health(),
            "tools": self.tool_registry.list_tools(),
            "mcp_servers": self.mcp_server_registry.list(),
            "a2a_agents": self.a2a_agent_registry.list(),
            "workflows": self.workflow_registry.list(),
        }

    @self.fastapi.get("/health/live")
    async def liveness() -> dict[str, str]:
        """仅确认API进程和事件循环仍能响应。"""
        return {"status": "alive"}

    @self.fastapi.get("/health/ready", response_model=None)
    async def readiness() -> Any:
        """检查接收业务流量所依赖的数据库和向量库。"""
        checks: dict[str, str] = {}
        errors: dict[str, str] = {}

        async def check(name: str, operation) -> None:
            try:
                await asyncio.wait_for(
                    operation(),
                    timeout=5,
                )
                checks[name] = "ok"
            except Exception as error:
                checks[name] = "failed"
                errors[name] = type(error).__name__

        if self.system_management_service is not None:
            await check(
                "database",
                self.system_management_service.database.health_check,
            )
            quota_health = getattr(
                self.runtime.quota_manager,
                "health_check",
                None,
            )
            if quota_health is not None:
                await check("quota_store", quota_health)
            await check(
                "security_store",
                self.security_manager.health_check,
            )
        if self.vector_store is not None:
            await check("vector_store", self.vector_store.health_check)
        payload = {
            "status": "ready" if not errors else "not_ready",
            "checks": checks,
            "errors": errors,
        }
        if errors:
            return JSONResponse(
                status_code=503,
                content=payload,
            )
        return payload

    @self.fastapi.post("/v1/agents/run", response_model=None)
    async def run_agent(payload: AgentRunRequest, request: Request) -> Any:
        principal = self._authenticate(request)
        self._authorize_agent(principal, payload.agent)
        runtime_request = self._runtime_request(
            payload,
            principal,
        )

        with self.container.scope():
            result = await self.runtime.run(runtime_request)

        response = {
            "success": result.success,
            "task_id": result.metadata.get("task_id"),
            "request_id": result.metadata.get("request_id"),
            "trace_id": result.metadata.get("trace_id"),
            "content": result.content,
            "tool_calls": [
                {
                    "id": call.id,
                    "name": call.name,
                    "arguments": call.arguments,
                    "result": call.result,
                    "finished": call.finished,
                }
                for call in result.tool_calls
            ],
            "metadata": result.metadata,
            "error": result.error,
            "elapsed": result.elapsed,
        }

        if result.success:
            return response

        error_code = result.metadata.get("error_code", "INTERNAL_ERROR")
        status_code = self._error_status(str(error_code))
        return JSONResponse(status_code=status_code, content=response)

    @self.fastapi.get("/v1/tasks/{task_id}")
    async def get_task(task_id: str, request: Request) -> dict[str, Any]:
        """查询单个任务的当前状态和最终结果摘要。"""
        task = await self.task_manager.get(task_id)
        if task is None:
            raise HTTPException(
                status_code=404,
                detail="Task not found.",
            )
        self._authorize_task(
            self._authenticate(request),
            task,
        )
        return self._task_response(task)

    @self.fastapi.post(
        "/v1/tasks",
        status_code=202,
    )
    async def submit_task(payload: AgentRunRequest, request: Request) -> dict[str, Any]:
        """提交后台Agent任务并立即返回任务标识。"""
        principal = self._authenticate(request)
        self._authorize_agent(principal, payload.agent)
        runtime_request = self._runtime_request(
            payload,
            principal,
        )
        task = await self.runtime.submit(runtime_request)
        return self._task_response(task)

    @self.fastapi.get("/v1/tasks")
    async def list_tasks(request: Request, limit: int = 100) -> dict[str, Any]:
        """查询最近任务。"""
        tasks = await self.task_manager.list(limit=limit)
        principal = self._authenticate(request)
        if principal is not None and "platform_admin" not in principal.roles:
            tasks = [
                task
                for task in tasks
                if task.metadata.get("tenant_id") == principal.tenant_id
            ]
        return {"items": [self._task_response(task) for task in tasks]}

    @self.fastapi.post(
        "/v1/tasks/{task_id}/cancel",
        status_code=202,
    )
    async def cancel_task(task_id: str, request: Request) -> dict[str, Any]:
        """请求取消正在运行的后台任务。"""
        existing = await self.task_manager.get(task_id)
        if existing is None:
            raise HTTPException(
                status_code=404,
                detail="Task not found.",
            )
        self._authorize_task(
            self._authenticate(request),
            existing,
        )
        try:
            task = await self.runtime.cancel(task_id)
        except ValueError as error:
            raise HTTPException(
                status_code=409,
                detail=str(error),
            ) from error
        if task is None:
            raise HTTPException(
                status_code=404,
                detail="Task not found.",
            )
        return {
            "task_id": task.task_id,
            "status": task.status.value,
            "cancellation_requested": True,
        }

    @self.fastapi.post(
        "/v1/tasks/{task_id}/retry",
        status_code=202,
    )
    async def retry_task(task_id: str, request: Request) -> dict[str, Any]:
        """使用原请求创建一次新的重试任务。"""
        existing = await self.task_manager.get(task_id)
        if existing is None:
            raise HTTPException(
                status_code=404,
                detail="Task not found.",
            )
        self._authorize_task(
            self._authenticate(request),
            existing,
        )
        try:
            task = await self.runtime.retry(task_id)
        except ValueError as error:
            raise HTTPException(
                status_code=409,
                detail=str(error),
            ) from error
        if task is None:
            raise HTTPException(
                status_code=404,
                detail="Task not found.",
            )
        return self._task_response(task)

    @self.fastapi.get("/v1/tasks/{task_id}/events")
    async def get_task_events(task_id: str, request: Request) -> dict[str, Any]:
        """查询任务生命周期事件。"""
        task = await self.task_manager.get(task_id)
        if task is None:
            raise HTTPException(
                status_code=404,
                detail="Task not found.",
            )
        self._authorize_task(
            self._authenticate(request),
            task,
        )
        return {
            "task_id": task.task_id,
            "events": [
                {
                    "type": event.type,
                    "timestamp": (event.timestamp.isoformat()),
                    "data": event.data,
                }
                for event in task.events
            ],
        }

    @self.fastapi.get("/v1/tasks/{task_id}/events/stream")
    async def stream_task_events(
        task_id: str,
        request: Request,
        after: int = 0,
    ) -> StreamingResponse:
        """以SSE实时发送真实任务事件，并支持按事件序号续传。"""
        task = await self.task_manager.get(task_id)
        if task is None:
            raise HTTPException(
                status_code=404,
                detail="Task not found.",
            )
        self._authorize_task(
            self._authenticate(request),
            task,
        )
        last_event_id = request.headers.get("last-event-id")
        if last_event_id:
            try:
                after = max(after, int(last_event_id))
            except ValueError as error:
                raise HTTPException(
                    status_code=400,
                    detail="Last-Event-ID must be an integer.",
                ) from error
        if after < 0:
            raise HTTPException(
                status_code=422,
                detail="after must be greater than or equal to 0.",
            )

        async def generate():
            cursor = after
            last_heartbeat = time.monotonic()
            while True:
                if await request.is_disconnected():
                    return
                current, new_events = await self.task_manager.poll(
                    task_id, after=cursor
                )
                if current is None:
                    return
                for event in new_events:
                    cursor += 1
                    payload = {
                        "id": cursor,
                        "task_id": current.task_id,
                        "status": current.status.value,
                        "type": event.type,
                        "timestamp": event.timestamp.isoformat(),
                        "data": event.data,
                    }
                    yield (
                        f"id: {cursor}\n"
                        f"event: {event.type}\n"
                        f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    )
                    last_heartbeat = time.monotonic()
                if current.terminal:
                    return
                now = time.monotonic()
                if now - last_heartbeat >= 15:
                    yield ": heartbeat\n\n"
                    last_heartbeat = now
                await asyncio.sleep(0.25)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @self.fastapi.get("/v1/tasks/{task_id}/trace")
    async def get_task_trace(task_id: str, request: Request) -> dict[str, Any]:
        """按任务查询完整Trace和Span。"""
        task = await self.task_manager.get(task_id)
        if task is None:
            raise HTTPException(
                status_code=404,
                detail="Task not found.",
            )
        self._authorize_task(
            self._authenticate(request),
            task,
        )
        trace = await self.trace_manager.load(task.trace_id)
        if trace is None:
            raise HTTPException(
                status_code=404,
                detail="Trace not found.",
            )
        return {
            "trace_id": trace.trace_id,
            "request_id": trace.request_id,
            "status": trace.status,
            "start_time": trace.start_time.isoformat(),
            "end_time": (trace.end_time.isoformat() if trace.end_time else None),
            "metadata": trace.metadata,
            "spans": [
                {
                    "span_id": span.span_id,
                    "parent_span_id": span.parent_span_id,
                    "name": span.name,
                    "status": span.status,
                    "start_time": span.start_time.isoformat(),
                    "end_time": (span.end_time.isoformat() if span.end_time else None),
                    "duration_ms": span.duration,
                    "metadata": span.metadata,
                    "error": span.error,
                }
                for span in trace.spans
            ],
        }
