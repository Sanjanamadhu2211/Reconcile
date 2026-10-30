import math
import time
from collections import deque
from collections.abc import Callable, Hashable
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, Request

from app.auth.dependencies import get_current_user
from app.config import get_settings
from app.models import User


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    hops = get_settings().trusted_proxy_count
    if hops == 0:
        return peer
    # Entries are appended by each proxy, so the ones counted from the right are trusted
    addresses = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",")]
    addresses = [address for address in addresses if address]
    return addresses[-hops] if len(addresses) >= hops else peer


# shortcut: in-memory, single uvicorn worker, move to the database or a shared store
# if the API ever runs more than one process
class LoginRateLimiter:
    def __init__(
        self,
        max_failures: int = 5,
        window_seconds: float = 15 * 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_failures = max_failures
        self._window_seconds = window_seconds
        self._clock = clock
        self._failures: dict[Hashable, deque[float]] = {}

    def is_blocked(self, key: Hashable) -> bool:
        return len(self._recent_failures(key)) >= self._max_failures

    def record_failure(self, key: Hashable) -> None:
        self._failures.setdefault(key, deque()).append(self._clock())

    def _recent_failures(self, key: Hashable) -> deque[float]:
        failures = self._failures.get(key, deque())
        cutoff = self._clock() - self._window_seconds
        while failures and failures[0] <= cutoff:
            failures.popleft()
        if not failures:
            self._failures.pop(key, None)
        return failures


login_limiter = LoginRateLimiter()


# shortcut: idle buckets are never evicted; bound the key space or move to a shared store
# before many users or addresses hit the API
class RequestRateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._hits: dict[Hashable, deque[float]] = {}

    def check(self, key: Hashable, limit: int, window_seconds: float) -> int:
        # Returns 0 and records the hit when allowed, else the whole seconds to wait
        now = self._clock()
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - window_seconds:
            hits.popleft()
        if len(hits) >= limit:
            return math.ceil(hits[0] + window_seconds - now)
        hits.append(now)
        return 0

    def clear(self) -> None:
        self._hits.clear()


request_limiter = RequestRateLimiter()


def rate_limit(name: str, limit: int, window_seconds: float, key: Literal["user", "ip"] = "user"):
    def enforce(bucket: Hashable) -> None:
        retry_after = request_limiter.check((name, bucket), limit, window_seconds)
        if retry_after:
            raise HTTPException(
                status_code=429,
                detail="Too many requests, try again later",
                headers={"Retry-After": str(retry_after)},
            )

    if key == "ip":

        def limit_by_ip(request: Request) -> None:
            enforce(client_ip(request))

        return limit_by_ip

    def limit_by_user(user: Annotated[User, Depends(get_current_user)]) -> None:
        enforce(user.id)

    return limit_by_user
