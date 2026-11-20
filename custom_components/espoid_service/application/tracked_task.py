"""Track service-owned work without tying its lifetime to the waiting caller."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

Result = TypeVar("Result")


async def run_tracked_task(
    work: Coroutine[Any, Any, Result],
    tasks: set[asyncio.Task[Result]],
    *,
    create_task: Callable[
        [Coroutine[Any, Any, Result]], asyncio.Task[Result]
    ] = asyncio.create_task,
) -> Result:
    """Start once, retain until completion and protect against caller cancellation.

    The owner supplies its task set and decides whether shutdown waits or cancels.
    Observing a failure here prevents an unhandled-task warning after disconnect;
    a caller still waiting receives the original exception from await.
    """
    task = create_task(work)
    tasks.add(task)
    task.add_done_callback(lambda done: _finish_task(tasks, done))
    return await asyncio.shield(task)


def _finish_task(tasks: set[asyncio.Task[Result]], task: asyncio.Task[Result]) -> None:
    tasks.discard(task)
    if not task.cancelled():
        task.exception()
