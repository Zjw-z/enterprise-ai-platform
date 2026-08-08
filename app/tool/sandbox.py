"""Tool能力沙箱：集中控制网络、文件和子进程访问。"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import shutil
import socket
from abc import abstractmethod
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.tool.base import BaseTool
from app.tool.schema import ToolPolicy, ToolResult


class SandboxViolationError(PermissionError):
    """工具尝试使用未授权能力。"""


class SandboxContext:
    """受策略约束的Tool I/O能力集合。"""

    def __init__(self, policy: ToolPolicy) -> None:
        self.policy = policy

    def validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise SandboxViolationError(
                "Only HTTP(S) network access is supported."
            )
        host = (parsed.hostname or "").casefold()
        allowed = {
            item.casefold()
            for item in self.policy.allowed_network_domains
        }
        if not self.policy.network_access:
            raise SandboxViolationError(
                "Network access is disabled for this tool."
            )
        if (
            "*" not in allowed
            and host not in allowed
            and not any(
                host.endswith(f".{domain}")
                for domain in allowed
            )
        ):
            raise SandboxViolationError(
                f"Network domain is not allowed: {host}"
            )

    async def http_request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        self.validate_url(url)
        await self._validate_resolved_addresses(url)
        async with httpx.AsyncClient(
            timeout=self.policy.io_timeout_seconds,
            follow_redirects=False,
        ) as client:
            async with client.stream(method, url, **kwargs) as response:
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > self.policy.max_result_bytes:
                        raise SandboxViolationError(
                            "HTTP response exceeds sandbox output limit."
                        )
                return httpx.Response(
                    status_code=response.status_code,
                    headers=response.headers,
                    content=bytes(content),
                    request=response.request,
                )

    async def _validate_resolved_addresses(self, url: str) -> None:
        """阻止域名解析到本机、私网、链路本地或保留地址。"""
        if self.policy.allow_private_network:
            return
        parsed = urlparse(url)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            addresses = await asyncio.get_running_loop().getaddrinfo(
                host,
                port,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as error:
            raise SandboxViolationError(
                f"Network host cannot be resolved: {host}"
            ) from error
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            ):
                raise SandboxViolationError(
                    f"Private or reserved network address is denied: {ip}"
                )

    def resolve_read_path(self, path: str | Path) -> Path:
        return self._resolve_path(
            path,
            self.policy.allowed_read_paths,
            "read",
        )

    def resolve_write_path(self, path: str | Path) -> Path:
        return self._resolve_path(
            path,
            self.policy.allowed_write_paths,
            "write",
        )

    @staticmethod
    def _resolve_path(
        path: str | Path,
        roots: tuple[str, ...],
        operation: str,
    ) -> Path:
        resolved = Path(path).resolve()
        for root in roots:
            allowed_root = Path(root).resolve()
            if (
                resolved == allowed_root
                or allowed_root in resolved.parents
            ):
                return resolved
        raise SandboxViolationError(
            f"File {operation} path is not allowed: {resolved}"
        )

    async def read_text(
        self,
        path: str | Path,
        *,
        encoding: str = "utf-8",
    ) -> str:
        resolved = self.resolve_read_path(path)
        return await asyncio.to_thread(
            resolved.read_text,
            encoding=encoding,
        )

    async def write_text(
        self,
        path: str | Path,
        content: str,
        *,
        encoding: str = "utf-8",
    ) -> None:
        resolved = self.resolve_write_path(path)
        await asyncio.to_thread(
            resolved.write_text,
            content,
            encoding=encoding,
        )

    async def run_process(
        self,
        executable: str,
        *args: str,
    ) -> tuple[int, bytes, bytes]:
        if not self.policy.subprocess_access:
            raise SandboxViolationError(
                "Subprocess access is disabled for this tool."
            )
        resolved_executable = shutil.which(executable)
        allowed = {
            str(Path(item).resolve())
            if Path(item).is_absolute()
            else str(Path(found).resolve())
            for item in self.policy.allowed_executables
            if (found := shutil.which(item)) is not None
            or Path(item).is_absolute()
        }
        if (
            resolved_executable is None
            or str(Path(resolved_executable).resolve()) not in allowed
        ):
            raise SandboxViolationError(
                f"Executable is not allowed: {executable}"
            )
        environment = {
            name: os.environ[name]
            for name in self.policy.allowed_environment_variables
            if name in os.environ
        }
        process = await asyncio.create_subprocess_exec(
            resolved_executable,
            *args,
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.policy.io_timeout_seconds,
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            raise
        if (
            len(stdout) + len(stderr)
            > self.policy.max_process_output_bytes
        ):
            raise SandboxViolationError(
                "Subprocess output exceeds sandbox output limit."
            )
        return process.returncode or 0, stdout, stderr


class SandboxedTool(BaseTool):
    """需要平台能力沙箱的Tool基类。"""

    async def run(
        self,
        params: dict[str, Any],
    ) -> ToolResult:
        return await self.run_sandboxed(
            params,
            SandboxContext(self.policy),
        )

    @abstractmethod
    async def run_sandboxed(
        self,
        params: dict[str, Any],
        sandbox: SandboxContext,
    ) -> ToolResult:
        raise NotImplementedError
