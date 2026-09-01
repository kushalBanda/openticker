import asyncio
import time


class RateLimiter:
    def __init__(self, calls_per_second: float) -> None:
        self._min_interval = 1.0 / calls_per_second
        self._lock = asyncio.Lock()
        self._last_call: float | None = None

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if self._last_call is not None:
                elapsed = now - self._last_call
                wait = self._min_interval - elapsed
                if wait > 0:
                    await asyncio.sleep(wait)
            self._last_call = time.monotonic()
