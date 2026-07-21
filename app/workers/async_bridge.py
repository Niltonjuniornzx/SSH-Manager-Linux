"""Integração asyncio/qasync com Qt."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Coroutine, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def get_event_loop() -> asyncio.AbstractEventLoop:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.get_event_loop()


def create_task_safe(coro: Coroutine[Any, Any, T], *, name: str = "") -> asyncio.Task[T]:
    """Cria task e loga exceções não tratadas."""
    loop = get_event_loop()

    def _done(task: asyncio.Task[T]) -> None:
        try:
            exc = task.exception()
            if exc is not None and not isinstance(exc, asyncio.CancelledError):
                logger.error("Task %s falhou: %s", name or task.get_name(), exc, exc_info=exc)
        except asyncio.CancelledError:
            pass
        except asyncio.InvalidStateError:
            pass

    task = loop.create_task(coro, name=name or None)
    task.add_done_callback(_done)
    return task


async def run_async(coro: Coroutine[Any, Any, T]) -> T:
    return await coro


def schedule(coro: Coroutine[Any, Any, T], *, name: str = "") -> Optional[asyncio.Task[T]]:
    try:
        return create_task_safe(coro, name=name)
    except RuntimeError:
        logger.warning("Sem event loop para agendar task %s", name)
        return None
