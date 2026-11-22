"""Timeouts + retries with exponential backoff. Used around every external call."""
from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


async def with_retries(fn: Callable[[], Awaitable[T]], *, attempts: int = 2, timeout_s: float = 15,
                       base_delay_s: float = 0.5) -> T:
    last: Exception | None = None
    for i in range(attempts + 1):
        try:
            return await asyncio.wait_for(fn(), timeout=timeout_s)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - we re-raise after the last attempt
            last = e
            if i < attempts:
                await asyncio.sleep(base_delay_s * (2**i))
    assert last is not None
    raise last


_SECRET = re.compile(r"(key|token|secret|authorization)=[^&\s]+", re.I)


def scrub(msg: str) -> str:
    """Remove anything that looks like a credential before it reaches logs/events."""
    return _SECRET.sub(r"\1=***", msg)[:300]
