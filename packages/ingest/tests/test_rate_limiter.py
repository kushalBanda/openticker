import asyncio
import time

from ingest.core.rate_limiter import RateLimiter


async def test_acquire_throttles_to_configured_rate() -> None:
    limiter = RateLimiter(calls_per_second=10.0)
    start = time.monotonic()
    for _ in range(5):
        await limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.4


async def test_acquire_allows_concurrent_callers_without_deadlock() -> None:
    limiter = RateLimiter(calls_per_second=50.0)
    await asyncio.gather(*(limiter.acquire() for _ in range(5)))
