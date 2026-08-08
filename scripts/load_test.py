"""Dependency-free async load smoke test for the Agent Runtime API."""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time

import httpx


async def run(args: argparse.Namespace) -> int:
    semaphore = asyncio.Semaphore(args.concurrency)
    latencies: list[float] = []
    failures: list[str] = []
    headers = (
        {"X-API-Key": args.api_key}
        if args.api_key
        else {}
    )

    async with httpx.AsyncClient(
        base_url=args.base_url,
        timeout=args.timeout,
        headers=headers,
    ) as client:
        async def invoke(index: int) -> None:
            async with semaphore:
                started = time.perf_counter()
                try:
                    response = await client.post(
                        "/v1/agents/run",
                        json={
                            "agent": args.agent,
                            "message": f"{args.message} #{index}",
                            "session_id": f"load-{index}",
                        },
                    )
                    response.raise_for_status()
                    if not response.json().get("success"):
                        failures.append(
                            f"{index}: unsuccessful result"
                        )
                except Exception as error:
                    failures.append(f"{index}: {error}")
                finally:
                    latencies.append(
                        (time.perf_counter() - started) * 1000
                    )

        await asyncio.gather(
            *(invoke(index) for index in range(args.requests))
        )

    ordered = sorted(latencies)
    p95_index = max(0, int(len(ordered) * 0.95) - 1)
    print(
        {
            "requests": args.requests,
            "failures": len(failures),
            "success_rate": (
                (args.requests - len(failures)) / args.requests
            ),
            "average_ms": round(statistics.mean(latencies), 2),
            "p95_ms": round(ordered[p95_index], 2),
        }
    )
    for failure in failures[:10]:
        print(failure)
    return 1 if failures else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--agent", required=True)
    parser.add_argument("--message", default="请回复健康检查成功")
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--api-key")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(parse_args())))
