"""Thread offloading that never abandons a running subprocess-owning worker."""

import asyncio
import contextlib
import contextvars
import functools
from collections.abc import Callable
from typing import Any


async def to_thread_joined(func: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
    """Keep a subprocess-owning worker joined to its caller until it exits."""
    loop = asyncio.get_running_loop()
    context = contextvars.copy_context()
    call = functools.partial(context.run, func, *args, **kwargs)
    # Executor Futures escape loop-wide task cancellation, so the thread is joined before the slot frees.
    worker = loop.run_in_executor(None, call)
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        with contextlib.suppress(Exception):
            await _wait_ignoring_cancellation(worker)
        raise


async def _wait_ignoring_cancellation(future: asyncio.Future) -> Any:
    """Wait for already-started critical work despite repeated cancellation."""
    while not future.done():
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            continue
    return future.result()
