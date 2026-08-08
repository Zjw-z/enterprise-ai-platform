"""FastAPI接入层与真实Runtime调用链集成测试。"""

import asyncio
import base64
import hashlib
import hmac
import json
import time

import httpx

from app.agent import (
    AgentConfig,
    AgentContext,
    AgentResult,
    BaseAgent,
)
from app.bootstrap import Bootstrap


class ApiEchoAgent(BaseAgent):
    """将API输入和上下文信息回显的集成测试Agent。"""

    def __init__(self) -> None:
        super().__init__(
            AgentConfig(
                name="api-echo",
                memory_enabled=False,
            )
        )

    async def execute(
        self,
        context: AgentContext,
    ) -> AgentResult:
        return AgentResult(
            content=f"echo:{context.user_input}",
            metadata={
                "session_id": context.session_id,
                "user_id": context.user_id,
                "variables": context.variables,
                "tenant_id": context.metadata.get("tenant_id"),
                "principal_id": context.metadata.get(
                    "principal_id"
                ),
            },
        )


class ApiSlowAgent(BaseAgent):
    """用于验证后台提交和真实取消的慢任务Agent。"""

    def __init__(self) -> None:
        super().__init__(
            AgentConfig(
                name="api-slow",
                memory_enabled=False,
            )
        )

    async def execute(
        self,
        context: AgentContext,
    ) -> AgentResult:
        await asyncio.sleep(10)
        return AgentResult(content="late")


def _application(tmp_path=None):
    """通过真实Bootstrap组装测试Application。"""
    config = {
        "environment": "test",
        "log_level": "CRITICAL",
        "agents": [
            ApiEchoAgent(),
            ApiSlowAgent(),
        ],
    }
    if tmp_path is not None:
        # 仅需要验证持久化内容的测试使用独立临时库。
        config.update(
            {
                "system_database_url": (
                    "sqlite+aiosqlite:///"
                    f"{(tmp_path / 'api-system.db').as_posix()}"
                ),
                "system_database_schema_mode": "create_all",
            }
        )
    return Bootstrap(config).build()


def _secure_application():
    """创建启用API Key认证的双租户测试Application。"""
    return Bootstrap(
        {
            "environment": "test",
            "log_level": "CRITICAL",
            # 集成测试不启动ASGI lifespan，因此显式使用无外部依赖Adapter。
            "vector_store_backend": "none",
            "audit_backend": "in_memory",
            "agents": [
                ApiEchoAgent(),
                ApiSlowAgent(),
            ],
            "security_enabled": True,
            "api_principals": {
                "tenant-a-user": {
                    "api_key": "tenant-a-secret",
                    "tenant_id": "tenant-a",
                    "user_id": "user-a",
                    "roles": ["user"],
                    "allowed_agents": ["api-echo"],
                    "allowed_tools": ["*"],
                    "allowed_models": ["*"],
                },
                "tenant-b-user": {
                    "api_key": "tenant-b-secret",
                    "tenant_id": "tenant-b",
                    "user_id": "user-b",
                    "roles": ["user"],
                    "allowed_agents": ["api-echo"],
                    "allowed_tools": ["*"],
                    "allowed_models": ["*"],
                },
            },
        }
    ).build()


def _jwt_application():
    """创建仅启用JWT认证的测试Application。"""
    return Bootstrap(
        {
            "environment": "test",
            "log_level": "CRITICAL",
            "vector_store_backend": "none",
            "audit_backend": "in_memory",
            "agents": [ApiEchoAgent()],
            "security_enabled": True,
            "api_principals": {},
            "security_jwt_secret": "jwt-test-secret",
            "security_jwt_issuer": "test-issuer",
            "security_jwt_audience": "test-audience",
        }
    ).build()


def _jwt(payload: dict) -> str:
    """生成测试用HS256 JWT。"""

    def encode(value: dict) -> str:
        raw = json.dumps(
            value,
            separators=(",", ":"),
        ).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    header = encode({"alg": "HS256", "typ": "JWT"})
    body = encode(payload)
    signature = hmac.new(
        b"jwt-test-secret",
        f"{header}.{body}".encode(),
        hashlib.sha256,
    ).digest()
    encoded_signature = (
        base64.urlsafe_b64encode(signature)
        .decode()
        .rstrip("=")
    )
    return f"{header}.{body}.{encoded_signature}"


def test_health_reports_registered_components() -> None:
    """健康检查应返回当前已注册Agent、模型和工具。"""

    async def scenario() -> None:
        application = _application()
        transport = httpx.ASGITransport(
            app=application.get_fastapi()
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert "api-echo" in body["agents"]
        assert isinstance(body["models"], list)
        assert isinstance(body["model_health"], dict)
        assert isinstance(body["tools"], list)

    asyncio.run(scenario())


def test_prometheus_metrics_use_route_templates() -> None:
    """指标应可抓取，且动态资源ID不能成为Prometheus标签。"""

    async def scenario() -> None:
        application = _application()
        transport = httpx.ASGITransport(
            app=application.get_fastapi()
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            await client.get("/v1/tasks/not-a-real-task")
            response = await client.get("/metrics")

        assert response.status_code == 200
        assert "eap_http_requests_total" in response.text
        assert (
            'route="/v1/tasks/{task_id}"'
            in response.text
        )
        assert "not-a-real-task" not in response.text

    asyncio.run(scenario())


def test_rerank_api_uses_registered_model() -> None:
    """Rerank能力应通过统一模型管理和HTTP接入层调用。"""

    async def scenario() -> None:
        application = _application()
        transport = httpx.ASGITransport(
            app=application.get_fastapi()
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/v1/rerank",
                json={
                    "model": "lexical-default",
                    "query": "上海天气",
                    "documents": [
                        "数据库设计",
                        "上海天气晴朗",
                    ],
                    "top_n": 1,
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["model"] == "lexical-v1"
        assert body["results"][0]["index"] == 1

    asyncio.run(scenario())


def test_database_prompt_writes_are_retired(tmp_path) -> None:
    """Prompt 必须归属 Agent 文件包，旧数据库写入口应明确停用。"""

    async def scenario() -> None:
        application = _application(tmp_path)
        await application.system_management_service.database.initialize()
        transport = httpx.ASGITransport(
            app=application.get_fastapi()
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            created = await client.post(
                "/v1/prompts/drafts",
                json={
                    "name": "managed-prompt",
                    "version": "1.0",
                    "template": "你好，{name}",
                    "variables": [{"name": "name", "type": "string"}],
                },
            )
            edited = await client.put(
                "/v1/prompts/managed-prompt/1.0/draft",
                json={
                    "name": "managed-prompt",
                    "version": "1.0",
                    "template": "欢迎，{name}",
                    "variables": [{"name": "name", "type": "string"}],
                },
            )
        await application.system_management_service.database.close()

        assert created.status_code == 410
        assert "Agent 文件包" in created.json()["detail"]
        assert edited.status_code == 410
        assert "Agent 文件包" in edited.json()["detail"]

    asyncio.run(scenario())


def test_model_profile_draft_can_be_edited_but_published_is_immutable(
    tmp_path,
) -> None:
    async def scenario() -> None:
        application = _application(tmp_path)
        await application.system_management_service.database.initialize()
        transport = httpx.ASGITransport(
            app=application.get_fastapi()
        )
        original = {
            "name": "editable-model",
            "version": "1.0",
            "description": "original",
            "provider": "openai_compatible",
            "model": "qwen-turbo",
            "base_url": "https://example.invalid/v1",
            "secret_ref": "env://MODEL_API_KEY",
            "parameters": {"temperature": 0.7},
        }
        updated = {
            **original,
            "description": "updated",
            "model": "qwen-plus",
            "parameters": {
                "temperature": 0.2,
                "max_tokens": 4096,
            },
        }
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            created = await client.post(
                "/v1/model-profiles",
                json=original,
            )
            edited = await client.put(
                "/v1/model-profiles/editable-model/1.0",
                json=updated,
            )
            published = await client.post(
                "/v1/model-profiles/editable-model/1.0/publish"
            )
            rejected = await client.put(
                "/v1/model-profiles/editable-model/1.0",
                json={**updated, "model": "qwen-max"},
            )
        await application.system_management_service.database.close()

        assert created.status_code == 200
        assert edited.status_code == 200
        assert edited.json()["model"] == "qwen-plus"
        assert edited.json()["parameters"] == {
            "temperature": 0.2,
            "max_tokens": 4096,
        }
        assert published.status_code == 200
        assert rejected.status_code == 409
        assert "Only draft" in rejected.json()["detail"]

    asyncio.run(scenario())


def test_agent_evaluation_dataset_lifecycle_api(tmp_path) -> None:
    """评测数据集应支持创建、版本快照和查询。"""

    async def scenario() -> None:
        application = _application(tmp_path)
        await application.system_management_service.database.initialize()
        transport = httpx.ASGITransport(
            app=application.get_fastapi()
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            created = await client.post(
                "/v1/agent-evaluation-datasets",
                json={
                    "name": "release-regression",
                    "description": "发布回归",
                },
            )
            dataset_id = created.json()["id"]
            version = await client.post(
                "/v1/agent-evaluation-datasets/"
                f"{dataset_id}/versions",
                json={
                    "version": "1.0",
                    "cases": [
                        {
                            "name": "hello",
                            "input": "hello",
                            "assertions": [
                                {
                                    "type": "contains",
                                    "value": "hello",
                                }
                            ],
                        }
                    ],
                    "gate": {
                        "minimum_pass_rate": 1.0
                    },
                },
            )
            datasets = await client.get(
                "/v1/agent-evaluation-datasets"
            )
        await application.system_management_service.database.close()

        assert created.status_code == 200
        assert version.status_code == 200
        assert version.json()["version"] == "1.0"
        assert datasets.status_code == 200
        assert datasets.json()[0]["active_version"] == "1.0"

    asyncio.run(scenario())


def test_agent_api_executes_full_runtime_chain() -> None:
    """HTTP请求应经过Runtime并返回统一AgentResult结构。"""

    async def scenario() -> None:
        application = _application()
        transport = httpx.ASGITransport(
            app=application.get_fastapi()
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/v1/agents/run",
                json={
                    "agent": "api-echo",
                    "message": "hello",
                    "session_id": "session-1",
                    "user_id": "user-1",
                    "parameters": {"language": "zh-CN"},
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["task_id"]
        assert body["request_id"]
        assert body["trace_id"]
        assert body["content"] == "echo:hello"
        assert body["metadata"]["session_id"] == "session-1"
        assert body["metadata"]["user_id"] == "user-1"
        assert body["metadata"]["variables"] == {
            "language": "zh-CN"
        }
        assert body["elapsed"] >= 0

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as query_client:
            task_response = await query_client.get(
                f"/v1/tasks/{body['task_id']}"
            )
            event_response = await query_client.get(
                f"/v1/tasks/{body['task_id']}/events"
            )
            stream_response = await query_client.get(
                f"/v1/tasks/{body['task_id']}/events/stream"
            )
            resumed_stream = await query_client.get(
                f"/v1/tasks/{body['task_id']}/events/stream",
                headers={"Last-Event-ID": "2"},
            )
            trace_response = await query_client.get(
                f"/v1/tasks/{body['task_id']}/trace"
            )

        assert task_response.status_code == 200
        task = task_response.json()
        assert task["status"] == "completed"
        assert task["result"]["content"] == "echo:hello"
        assert event_response.status_code == 200
        assert [
            event["type"]
            for event in event_response.json()["events"]
        ] == [
            "task.created",
            "task.started",
            "task.completed",
        ]
        assert stream_response.status_code == 200
        assert (
            stream_response.headers["content-type"]
            .startswith("text/event-stream")
        )
        assert stream_response.text.count("data: ") == 3
        assert "event: task.created" in stream_response.text
        assert "event: task.completed" in stream_response.text
        assert resumed_stream.text.count("data: ") == 1
        assert "id: 3" in resumed_stream.text
        assert "event: task.completed" in resumed_stream.text
        assert trace_response.status_code == 200
        trace = trace_response.json()
        assert trace["trace_id"] == body["trace_id"]
        assert trace["status"] == "ok"
        assert [
            span["name"]
            for span in trace["spans"]
        ] == [
            "runtime.execute",
            "agent.execute",
        ]
        assert all(
            span["status"] == "ok"
            for span in trace["spans"]
        )
        assert trace["spans"][1]["parent_span_id"] == (
            trace["spans"][0]["span_id"]
        )

    asyncio.run(scenario())


def test_agent_api_maps_missing_agent_to_404() -> None:
    """不存在的Agent应映射为404，而不是泄漏内部异常。"""

    async def scenario() -> None:
        application = _application()
        transport = httpx.ASGITransport(
            app=application.get_fastapi()
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/v1/agents/run",
                json={
                    "agent": "missing-agent",
                    "message": "hello",
                },
            )

        assert response.status_code == 404
        body = response.json()
        assert body["success"] is False
        assert body["metadata"]["error_code"] == (
            "AGENT_NOT_FOUND"
        )

    asyncio.run(scenario())


def test_agent_api_validates_request_body() -> None:
    """空消息应由API Schema在进入Runtime前拒绝。"""

    async def scenario() -> None:
        application = _application()
        transport = httpx.ASGITransport(
            app=application.get_fastapi()
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/v1/agents/run",
                json={
                    "agent": "api-echo",
                    "message": "",
                },
            )

        assert response.status_code == 422

    asyncio.run(scenario())


def test_background_task_submit_and_cancel_api() -> None:
    """后台任务接口应立即返回，并能取消真实执行协程。"""

    async def scenario() -> None:
        application = _application()
        transport = httpx.ASGITransport(
            app=application.get_fastapi()
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            submitted = await client.post(
                "/v1/tasks",
                json={
                    "agent": "api-slow",
                    "message": "hello",
                },
            )
            assert submitted.status_code == 202
            task_id = submitted.json()["task_id"]

            cancelled = await client.post(
                f"/v1/tasks/{task_id}/cancel"
            )
            assert cancelled.status_code == 202

            for _ in range(20):
                queried = await client.get(
                    f"/v1/tasks/{task_id}"
                )
                if queried.json()["status"] == "cancelled":
                    break
                await asyncio.sleep(0)

        assert queried.json()["status"] == "cancelled"

    asyncio.run(scenario())


def test_background_task_list_api() -> None:
    """任务列表接口应返回最近提交的后台任务。"""

    async def scenario() -> None:
        application = _application()
        transport = httpx.ASGITransport(
            app=application.get_fastapi()
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            submitted = await client.post(
                "/v1/tasks",
                json={
                    "agent": "api-echo",
                    "message": "hello",
                },
            )
            task_id = submitted.json()["task_id"]
            await asyncio.sleep(0)
            response = await client.get(
                "/v1/tasks",
                params={"limit": 10},
            )

        assert response.status_code == 200
        assert task_id in {
            item["task_id"]
            for item in response.json()["items"]
        }

    asyncio.run(scenario())


def test_security_requires_valid_api_key() -> None:
    """启用安全后缺失或错误凭据必须返回401。"""

    async def scenario() -> None:
        application = _secure_application()
        transport = httpx.ASGITransport(
            app=application.get_fastapi()
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            missing = await client.post(
                "/v1/agents/run",
                json={
                    "agent": "api-echo",
                    "message": "hello",
                },
            )
            invalid = await client.post(
                "/v1/agents/run",
                headers={"X-API-Key": "wrong"},
                json={
                    "agent": "api-echo",
                    "message": "hello",
                },
            )

        assert missing.status_code == 401
        assert invalid.status_code == 401

    asyncio.run(scenario())


def test_authenticated_identity_overrides_spoofed_payload() -> None:
    """客户端不能通过user_id或metadata伪造租户身份。"""

    async def scenario() -> None:
        application = _secure_application()
        transport = httpx.ASGITransport(
            app=application.get_fastapi()
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/v1/agents/run",
                headers={
                    "Authorization": (
                        "Bearer tenant-a-secret"
                    )
                },
                json={
                    "agent": "api-echo",
                    "message": "hello",
                    "user_id": "forged-user",
                    "metadata": {
                        "tenant_id": "forged-tenant",
                        "principal_id": "forged-principal",
                    },
                },
            )

        assert response.status_code == 200
        metadata = response.json()["metadata"]
        assert metadata["user_id"] == "user-a"
        assert metadata["tenant_id"] == "tenant-a"
        assert metadata["principal_id"] == "tenant-a-user"

    asyncio.run(scenario())


def test_security_enforces_agent_permission() -> None:
    """主体不能调用allowed_agents之外的Agent。"""

    async def scenario() -> None:
        application = _secure_application()
        transport = httpx.ASGITransport(
            app=application.get_fastapi()
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/v1/tasks",
                headers={"X-API-Key": "tenant-a-secret"},
                json={
                    "agent": "api-slow",
                    "message": "hello",
                },
            )

        assert response.status_code == 403

    asyncio.run(scenario())


def test_tenant_cannot_query_another_tenant_task() -> None:
    """任务查询必须执行可信租户隔离。"""

    async def scenario() -> None:
        application = _secure_application()
        transport = httpx.ASGITransport(
            app=application.get_fastapi()
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            submitted = await client.post(
                "/v1/tasks",
                headers={"X-API-Key": "tenant-a-secret"},
                json={
                    "agent": "api-echo",
                    "message": "hello",
                },
            )
            task_id = submitted.json()["task_id"]
            denied = await client.get(
                f"/v1/tasks/{task_id}",
                headers={"X-API-Key": "tenant-b-secret"},
            )

        assert denied.status_code == 403

    asyncio.run(scenario())


def test_hs256_jwt_authentication() -> None:
    """有效JWT应建立可信Principal，过期JWT必须返回401。"""

    async def scenario() -> None:
        application = _jwt_application()
        transport = httpx.ASGITransport(
            app=application.get_fastapi()
        )
        valid_token = _jwt(
            {
                "sub": "jwt-principal",
                "tenant_id": "jwt-tenant",
                "user_id": "jwt-user",
                "roles": ["user"],
                "allowed_agents": ["api-echo"],
                "iss": "test-issuer",
                "aud": "test-audience",
                "exp": time.time() + 60,
            }
        )
        expired_token = _jwt(
            {
                "sub": "jwt-principal",
                "tenant_id": "jwt-tenant",
                "iss": "test-issuer",
                "aud": "test-audience",
                "exp": time.time() - 1,
            }
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            valid = await client.post(
                "/v1/agents/run",
                headers={
                    "Authorization": f"Bearer {valid_token}"
                },
                json={
                    "agent": "api-echo",
                    "message": "hello",
                },
            )
            expired = await client.post(
                "/v1/agents/run",
                headers={
                    "Authorization": f"Bearer {expired_token}"
                },
                json={
                    "agent": "api-echo",
                    "message": "hello",
                },
            )

        assert valid.status_code == 200
        assert valid.json()["metadata"]["tenant_id"] == (
            "jwt-tenant"
        )
        assert expired.status_code == 401

    asyncio.run(scenario())


def test_principal_rate_limit_returns_429() -> None:
    """主体耗尽令牌后应收到429和Retry-After。"""

    async def scenario() -> None:
        application = Bootstrap(
            {
                "environment": "test",
                "log_level": "CRITICAL",
                "agents": [ApiEchoAgent()],
                "security_enabled": True,
                "api_principals": {
                    "limited": {
                        "api_key": "limited-secret",
                        "tenant_id": "tenant-limited",
                        "user_id": "user-limited",
                        "allowed_agents": ["api-echo"],
                        "requests_per_minute": 1,
                    }
                },
            }
        ).build()
        transport = httpx.ASGITransport(
            app=application.get_fastapi()
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            first = await client.post(
                "/v1/agents/run",
                headers={"X-API-Key": "limited-secret"},
                json={
                    "agent": "api-echo",
                    "message": "hello",
                },
            )
            second = await client.post(
                "/v1/agents/run",
                headers={"X-API-Key": "limited-secret"},
                json={
                    "agent": "api-echo",
                    "message": "hello",
                },
            )

        assert first.status_code == 200
        assert second.status_code == 429
        assert int(second.headers["retry-after"]) >= 1

    asyncio.run(scenario())


def test_audit_records_success_and_denied_requests() -> None:
    """HTTP审计应记录成功和认证失败结果，并支持租户查询。"""

    async def scenario() -> None:
        application = _secure_application()
        transport = httpx.ASGITransport(
            app=application.get_fastapi()
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            await client.post(
                "/v1/agents/run",
                headers={"X-API-Key": "tenant-a-secret"},
                json={
                    "agent": "api-echo",
                    "message": "hello",
                },
            )
            await client.post(
                "/v1/agents/run",
                headers={"X-API-Key": "wrong"},
                json={
                    "agent": "api-echo",
                    "message": "hello",
                },
            )
            audit = await client.get(
                "/v1/audit",
                headers={"X-API-Key": "tenant-a-secret"},
            )

        assert audit.status_code == 200
        items = audit.json()["items"]
        assert any(
            item["outcome"] == "success"
            and item["tenant_id"] == "tenant-a"
            for item in items
        )
        assert all(
            item["tenant_id"] in {None, "tenant-a"}
            for item in items
        )

    asyncio.run(scenario())


def test_workflow_api_runs_registered_agent_node() -> None:
    async def scenario() -> None:
        application = Bootstrap(
            {
                "environment": "test",
                "log_level": "CRITICAL",
                "agents": [ApiEchoAgent()],
                "workflows": [
                    {
                        "name": "agent-flow",
                        "version": "1",
                        "nodes": [
                            {
                                "id": "answer",
                                "type": "agent",
                                "agent": "api-echo",
                            }
                        ],
                    }
                ],
            }
        ).build()
        transport = httpx.ASGITransport(
            app=application.get_fastapi()
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/v1/workflows/agent-flow/executions",
                json={
                    "input": {"message": "hello"},
                    "background": False,
                },
            )
            listed = await client.get(
                "/v1/workflow-executions"
            )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "completed"
        assert (
            payload["outputs"]["answer"]["content"]
            == "echo:hello"
        )
        assert listed.status_code == 200
        assert listed.json()[0]["execution_id"] == (
            payload["execution_id"]
        )

    asyncio.run(scenario())


def test_workflow_api_approval_and_resume() -> None:
    async def scenario() -> None:
        application = Bootstrap(
            {
                "environment": "test",
                "log_level": "CRITICAL",
                "workflows": [
                    {
                        "name": "review-flow",
                        "version": "1",
                        "nodes": [
                            {
                                "id": "review",
                                "type": "approval",
                            }
                        ],
                    }
                ],
            }
        ).build()
        transport = httpx.ASGITransport(
            app=application.get_fastapi()
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            waiting = await client.post(
                "/v1/workflows/review-flow/executions",
                json={"input": {}, "background": False},
            )
            approvals = await client.get(
                "/v1/workflow-approvals"
            )
            approval_id = approvals.json()[0][
                "approval_id"
            ]
            approved = await client.post(
                f"/v1/workflow-approvals/{approval_id}/approve",
                json={},
            )
            resumed = await client.post(
                "/v1/workflow-executions/"
                f"{waiting.json()['execution_id']}/resume"
            )

        assert waiting.json()["status"] == "waiting_approval"
        assert approved.json()["status"] == "approved"
        assert resumed.json()["status"] == "completed"

    asyncio.run(scenario())


def test_asset_management_and_agent_release_api() -> None:
    async def scenario() -> None:
        application = Bootstrap(
            {
                "environment": "test",
                "log_level": "CRITICAL",
                "agents": [ApiEchoAgent()],
            }
        ).build()
        transport = httpx.ASGITransport(
            app=application.get_fastapi()
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            agents = await client.get("/v1/agents")
            tools = await client.get("/v1/tools")
            models = await client.get("/v1/models")
            evaluated = await client.post(
                "/v1/agents/api-echo/evaluate",
                json={
                    "version": "1",
                    "cases": [
                        {
                            "input": "hello",
                            "expected_contains": "echo:hello",
                        }
                    ],
                },
            )
            published = await client.post(
                "/v1/agents/api-echo/publish",
                json={
                    "version": "1",
                    "report_id": evaluated.json()[
                        "report_id"
                    ],
                },
            )

        assert agents.status_code == 200
        assert any(
            agent["name"] == "api-echo"
            for agent in agents.json()
        )
        assert tools.status_code == 200
        assert models.status_code == 200
        assert evaluated.json()["passed"] is True
        assert published.json()["status"] == "published"

    asyncio.run(scenario())


def test_memory_api_uses_authenticated_user_scope() -> None:
    async def scenario() -> None:
        application = _secure_application()
        namespace = application.memory_manager.build_namespace(
            tenant_id="tenant-a",
            user_id="user-a",
            agent_id="api-echo",
        )
        await application.memory_manager.remember(
            "preference",
            "prefers concise answers",
            namespace=namespace,
        )
        transport = httpx.ASGITransport(
            app=application.get_fastapi()
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            found = await client.post(
                "/v1/memory/api-echo/search",
                headers={"X-API-Key": "tenant-a-secret"},
                json={
                    "query": "concise",
                    "tenant_id": "spoofed",
                    "user_id": "spoofed",
                },
            )
            updated = await client.put(
                "/v1/memory/api-echo/preference",
                headers={"X-API-Key": "tenant-a-secret"},
                json={
                    "content": "prefers detailed answers",
                    "memory_type": "preference",
                    "confidence": 0.95,
                    "tenant_id": "spoofed",
                    "user_id": "spoofed",
                },
            )
            listed = await client.get(
                "/v1/memory/api-echo",
                headers={"X-API-Key": "tenant-a-secret"},
            )
            deleted = await client.delete(
                "/v1/memory/api-echo/preference",
                headers={"X-API-Key": "tenant-a-secret"},
            )
            empty = await client.post(
                "/v1/memory/api-echo/search",
                headers={"X-API-Key": "tenant-a-secret"},
                json={"query": "concise"},
            )

        assert found.status_code == 200
        assert found.json()[0]["key"] == "preference"
        assert updated.json()["action"] == "updated"
        assert listed.json()[0]["content"] == (
            "prefers detailed answers"
        )
        assert listed.json()[0]["confidence"] == 0.95
        assert deleted.json() == {"deleted": True}
        assert empty.json() == []

    asyncio.run(scenario())
