"""Tool能力沙箱测试。"""

from pathlib import Path

import pytest

from app.tool import (
    SandboxContext,
    SandboxedTool,
    SandboxViolationError,
    ToolPolicy,
    ToolResult,
    ToolSchema,
)


class FileSandboxTool(SandboxedTool):
    name = "file-sandbox"

    def __init__(self, policy: ToolPolicy) -> None:
        self.policy = policy
        super().__init__()

    def schema(self) -> ToolSchema:
        return ToolSchema(name=self.name)

    async def run_sandboxed(
        self,
        params: dict,
        sandbox: SandboxContext,
    ) -> ToolResult:
        content = await sandbox.read_text(params["path"])
        return ToolResult(data=content)


def test_sandbox_restricts_network_domains() -> None:
    sandbox = SandboxContext(
        ToolPolicy(
            sandbox_required=True,
            network_access=True,
            allowed_network_domains=("api.example.com",),
        )
    )

    sandbox.validate_url("https://api.example.com/v1")
    with pytest.raises(
        SandboxViolationError,
        match="not allowed",
    ):
        sandbox.validate_url("https://evil.example/v1")


@pytest.mark.asyncio
async def test_sandbox_restricts_file_roots(
    tmp_path: Path,
) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    source = allowed / "input.txt"
    source.write_text("ok", encoding="utf-8")
    tool = FileSandboxTool(
        ToolPolicy(
            sandbox_required=True,
            allowed_read_paths=(str(allowed),),
        )
    )

    result = await tool.run({"path": str(source)})

    assert result.data == "ok"
    with pytest.raises(
        SandboxViolationError,
        match="not allowed",
    ):
        await tool.run(
            {"path": str(tmp_path / "outside.txt")}
        )


@pytest.mark.asyncio
async def test_sandbox_disables_subprocess_by_default() -> None:
    sandbox = SandboxContext(ToolPolicy())

    with pytest.raises(
        SandboxViolationError,
        match="disabled",
    ):
        await sandbox.run_process("python", "--version")


@pytest.mark.asyncio
async def test_sandbox_denies_private_network_after_dns_resolution() -> None:
    sandbox = SandboxContext(
        ToolPolicy(
            sandbox_required=True,
            network_access=True,
            allowed_network_domains=("localhost",),
        )
    )

    with pytest.raises(
        SandboxViolationError,
        match="Private or reserved",
    ):
        await sandbox._validate_resolved_addresses(
            "http://localhost/health"
        )
