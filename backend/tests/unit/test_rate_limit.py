from app.auth.rate_limit import LoginRateLimiter


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_blocks_after_five_failures_until_the_window_passes():
    clock = FakeClock()
    limiter = LoginRateLimiter(max_failures=5, window_seconds=900, clock=clock)

    for _ in range(5):
        assert not limiter.is_blocked("key")
        limiter.record_failure("key")

    clock.now = 899
    assert limiter.is_blocked("key")

    clock.now = 900
    assert not limiter.is_blocked("key")


def test_failures_are_counted_per_key():
    limiter = LoginRateLimiter(max_failures=1, clock=FakeClock())

    limiter.record_failure("first")

    assert limiter.is_blocked("first")
    assert not limiter.is_blocked("second")
