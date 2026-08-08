from app.core.security import Principal, SecurityManager


class DepartmentPolicy:
    def authorize(
        self,
        principal,
        *,
        action,
        resource_type,
        resource,
        context,
    ):
        if resource_type != "agent":
            return None
        return context.get("department") == "finance"


def test_abac_policy_can_deny_default_allow():
    manager = SecurityManager(
        enabled=False,
        authorization_policies=[DepartmentPolicy()],
    )
    principal = Principal(
        principal_id="p",
        tenant_id="t",
        user_id="u",
        allowed_agents=frozenset({"*"}),
    )

    assert manager.authorize_agent(
        principal,
        "finance-agent",
        {"department": "finance"},
    )
    assert not manager.authorize_agent(
        principal,
        "finance-agent",
        {"department": "sales"},
    )
