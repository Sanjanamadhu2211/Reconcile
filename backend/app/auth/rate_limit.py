import time
from collections import deque
from collections.abc import Callable, Hashable


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
