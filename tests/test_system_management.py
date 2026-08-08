import asyncio

import httpx

from app.bootstrap import Bootstrap


def _application(tmp_path, *, security_enabled=False):
    return Bootstrap(
        {
            "environment": "test",
            "log_level": "CRITICAL",
            "system_database_url": (
                "sqlite+aiosqlite:///"
                f"{(tmp_path / 'system.db').as_posix()}"
            ),
            # config.test.yaml面向真实联调库，默认只校验迁移；
            # 此处是测试专属临时库，需要由夹具自动创建表结构。
            "system_database_schema_mode": "create_all",
            # CORS单测不运行lifespan，审计使用进程内测试Adapter。
            "audit_backend": "in_memory",
            "system_jwt_secret": (
                "test-system-secret-with-at-least-32-characters"
            ),
            "system_initial_admin_password": "admin123",
            "security_enabled": security_enabled,
            "api_principals": {},
        }
    ).build()


def test_login_returns_dynamic_menu_and_permissions(
    tmp_path,
) -> None:
    async def scenario():
        application = _application(tmp_path)
        transport = httpx.ASGITransport(
            app=application.get_fastapi()
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            login = await client.post(
                "/v1/auth/login",
                json={
                    "username": "admin",
                    "password": "admin123",
                    "tenant_id": "default",
                },
            )
            token = login.json()["access_token"]
            headers = {
                "Authorization": f"Bearer {token}"
            }
            me = await client.get(
                "/v1/me",
                headers=headers,
            )
            menus = await client.get(
                "/v1/me/menus",
                headers=headers,
            )
        await application.system_management_service.database.close()

        assert login.status_code == 200
        assert me.json()["is_superuser"] is True
        assert "*" in me.json()["permissions"]
        assert any(
            item["code"] == "system"
            for item in menus.json()
        )
        assert any(
            item["code"] == "business"
            for item in menus.json()
        )
        ai_menu = next(
            item
            for item in menus.json()
            if item["code"] == "ai-management"
        )
        assert any(
            item["code"] == "ai-agent-debug"
            and item["path"] == "/ai/agent-debug"
            for item in ai_menu["children"]
        )
        assert [
            item["code"] for item in ai_menu["children"]
        ] == [
            "ai-models",
            "ai-prompts",
            "ai-tools",
            "ai-mcp-tools",
            "ai-knowledge",
            "ai-agents",
                "ai-workflows",
                "ai-agent-debug",
                "ai-memory",
                "ai-evaluations",
            "ai-approvals",
        ]

    asyncio.run(scenario())


def test_role_user_and_menu_crud(tmp_path) -> None:
    async def scenario():
        application = _application(tmp_path)
        transport = httpx.ASGITransport(
            app=application.get_fastapi()
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            login = await client.post(
                "/v1/auth/login",
                json={
                    "username": "admin",
                    "password": "admin123",
                },
            )
            headers = {
                "Authorization": (
                    f"Bearer {login.json()['access_token']}"
                )
            }
            menu = await client.post(
                "/v1/system/menus",
                headers=headers,
                json={
                    "name": "测试业务",
                    "code": "business-test",
                    "menu_type": "page",
                    "path": "/business/test",
                    "component": "business/test/index",
                    "permission": "business:test:use",
                    "module": "business",
                },
            )
            role = await client.post(
                "/v1/system/roles",
                headers=headers,
                json={
                    "name": "测试用户",
                    "code": "test_user",
                    "menu_ids": [menu.json()["id"]],
                    "permissions": ["business:test:use"],
                },
            )
            user = await client.post(
                "/v1/system/users",
                headers=headers,
                json={
                    "username": "tester",
                    "display_name": "测试人员",
                    "password": "tester123",
                    "role_ids": [role.json()["id"]],
                },
            )
            user_login = await client.post(
                "/v1/auth/login",
                json={
                    "username": "tester",
                    "password": "tester123",
                },
            )
            user_headers = {
                "Authorization": (
                    "Bearer "
                    f"{user_login.json()['access_token']}"
                )
            }
            user_menus = await client.get(
                "/v1/me/menus",
                headers=user_headers,
            )
            permissions = await client.get(
                "/v1/system/permissions",
                headers=headers,
            )
            assigned_role_delete = await client.delete(
                f"/v1/system/roles/{role.json()['id']}",
                headers=headers,
            )
            await client.delete(
                f"/v1/system/users/{user.json()['id']}",
                headers=headers,
            )
            role_delete = await client.delete(
                f"/v1/system/roles/{role.json()['id']}",
                headers=headers,
            )
        await application.system_management_service.database.close()

        assert menu.status_code == 200
        assert role.status_code == 200
        assert user.status_code == 200
        assert user_login.status_code == 200
        assert user_menus.json()[0]["code"] == "business-test"
        assert any(
            item["code"] == "business:test:use"
            for item in permissions.json()
        )
        assert assigned_role_delete.status_code == 400
        assert role_delete.status_code == 200

    asyncio.run(scenario())


def test_configured_frontend_origin_has_cors_headers(
    tmp_path,
) -> None:
    async def scenario():
        application = _application(tmp_path)
        transport = httpx.ASGITransport(
            app=application.get_fastapi()
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.options(
                "/v1/auth/login",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "POST",
                },
            )
        await application.system_management_service.database.close()

        assert response.status_code == 200
        assert (
            response.headers["access-control-allow-origin"]
            == "http://localhost:3000"
        )

    asyncio.run(scenario())


def test_refresh_token_is_rotated_and_logout_revokes(
    tmp_path,
) -> None:
    async def scenario():
        application = _application(tmp_path)
        transport = httpx.ASGITransport(
            app=application.get_fastapi()
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            login = await client.post(
                "/v1/auth/login",
                json={
                    "username": "admin",
                    "password": "admin123",
                },
            )
            old_refresh = login.json()["refresh_token"]
            refreshed = await client.post(
                "/v1/auth/refresh",
                json={"refresh_token": old_refresh},
            )
            old_again = await client.post(
                "/v1/auth/refresh",
                json={"refresh_token": old_refresh},
            )
            new_refresh = refreshed.json()["refresh_token"]
            await client.post(
                "/v1/auth/logout",
                headers={
                    "Authorization": (
                        "Bearer "
                        f"{refreshed.json()['access_token']}"
                    )
                },
                json={"refresh_token": new_refresh},
            )
            after_logout = await client.post(
                "/v1/auth/refresh",
                json={"refresh_token": new_refresh},
            )
        await application.system_management_service.database.close()

        assert refreshed.status_code == 200
        assert old_again.status_code == 401
        assert after_logout.status_code == 401

    asyncio.run(scenario())
