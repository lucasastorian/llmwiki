"""Executor helpers whose blocking work always finishes, even under cancellation."""

import asyncio
import contextlib
import contextvars
import functools
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")


def executor_future(func: Callable[..., T], /, *args: Any, **kwargs: Any) -> asyncio.Future[T]:
    """Start blocking work on the default executor with the caller's contextvars."""
    loop = asyncio.get_running_loop()
    context = contextvars.copy_context()
    call = functools.partial(context.run, func, *args, **kwargs)
    return loop.run_in_executor(None, call)


async def wait_ignoring_cancellation(future: asyncio.Future[T]) -> T:
    """Wait for already-started cleanup/critical work despite repeated cancellation."""
    while not future.done():
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            continue
    return future.result()


async def to_thread_joined(func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Like `asyncio.to_thread`, but on cancellation waits for the thread to finish before re-raising."""
    worker = executor_future(func, *args, **kwargs)
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        # Observe the worker's exception so it isn't reported as unretrieved; the cancel still wins.
        with contextlib.suppress(Exception):
            await wait_ignoring_cancellation(worker)
        raise
