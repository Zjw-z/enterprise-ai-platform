"""Probe liveness/readiness behavior during a controlled dependency fault."""

from __future__ import annotations

import argparse

import httpx


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
    )
    parser.add_argument(
        "--expect-ready",
        choices=["yes", "no"],
        required=True,
    )
    args = parser.parse_args()

    live = httpx.get(f"{args.base_url}/health/live", timeout=10)
    ready = httpx.get(f"{args.base_url}/health/ready", timeout=10)
    expected_ready = args.expect_ready == "yes"
    print(
        {
            "liveness": live.status_code,
            "readiness": ready.status_code,
            "readiness_body": ready.json(),
        }
    )
    valid = (
        live.status_code == 200
        and (ready.status_code == 200) == expected_ready
    )
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
