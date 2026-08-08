import asyncio

from app.core.lifecycle import ApplicationLifecycle


def test_lifecycle_rolls_back_in_reverse_order() -> None:
    async def scenario() -> None:
        calls: list[str] = []
        lifecycle = ApplicationLifecycle()
        lifecycle.add_step(
            "one",
            lambda: calls.append("start-one"),
            lambda: calls.append("stop-one"),
        )

        def fail() -> None:
            calls.append("start-two")
            raise RuntimeError("boom")

        lifecycle.add_step("two", fail)
        lifecycle.add_finalizer(
            "always", lambda: calls.append("finalize")
        )
        try:
            await lifecycle.startup()
        except RuntimeError:
            pass
        else:
            raise AssertionError("Startup failure was not propagated.")
        assert calls == [
            "start-one",
            "start-two",
            "stop-one",
            "finalize",
        ]

    asyncio.run(scenario())


def test_lifecycle_startup_and_shutdown_are_idempotent() -> None:
    async def scenario() -> None:
        calls: list[str] = []
        lifecycle = ApplicationLifecycle()
        lifecycle.add_step(
            "worker",
            lambda: calls.append("start"),
            lambda: calls.append("stop"),
        )
        await lifecycle.startup()
        await lifecycle.startup()
        await lifecycle.shutdown()
        await lifecycle.shutdown()
        assert calls == ["start", "stop"]

    asyncio.run(scenario())
