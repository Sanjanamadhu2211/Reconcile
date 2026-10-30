import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.auth import rate_limit as rate_limit_module
from app.auth.rate_limit import RequestRateLimiter, client_ip, rate_limit
from app.config import Settings


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def make_request(headers: dict[str, str] | None = None, peer: str = "203.0.113.9") -> Request:
    raw = [(name.lower().encode(), value.encode()) for name, value in (headers or {}).items()]
    return Request({"type": "http", "headers": raw, "client": (peer, 4321)})


def trust_proxies(monkeypatch, count: int) -> None:
    monkeypatch.setattr(
        rate_limit_module, "get_settings", lambda: Settings(trusted_proxy_count=count)
    )


def test_client_ip_is_the_socket_peer_by_default(monkeypatch):
    trust_proxies(monkeypatch, 0)
    request = make_request({"X-Forwarded-For": "198.51.100.7"})

    assert client_ip(request) == "203.0.113.9"


def test_client_ip_takes_the_address_counted_from_the_right(monkeypatch):
    trust_proxies(monkeypatch, 1)
    request = make_request({"X-Forwarded-For": "10.0.0.1, 198.51.100.7"})

    assert client_ip(request) == "198.51.100.7"


def test_client_ip_ignores_spoofed_entries_on_the_left(monkeypatch):
    trust_proxies(monkeypatch, 1)
    request = make_request({"X-Forwarded-For": "1.2.3.4, 5.6.7.8, 198.51.100.7"})

    assert client_ip(request) == "198.51.100.7"


def test_client_ip_counts_two_proxies_from_the_right(monkeypatch):
    trust_proxies(monkeypatch, 2)
    request = make_request({"X-Forwarded-For": "1.2.3.4, 10.0.0.1, 198.51.100.7"})

    assert client_ip(request) == "10.0.0.1"


@pytest.mark.parametrize("header", [None, "", "  ,  "])
def test_client_ip_falls_back_to_the_peer_without_a_usable_header(monkeypatch, header):
    trust_proxies(monkeypatch, 1)
    headers = {} if header is None else {"X-Forwarded-For": header}

    assert client_ip(make_request(headers)) == "203.0.113.9"


def test_client_ip_falls_back_to_the_peer_when_the_header_is_shorter_than_the_proxy_count(
    monkeypatch,
):
    trust_proxies(monkeypatch, 2)
    request = make_request({"X-Forwarded-For": "198.51.100.7"})

    assert client_ip(request) == "203.0.113.9"


def test_limiter_allows_the_limit_and_blocks_the_next_hit():
    limiter = RequestRateLimiter(clock=FakeClock())

    assert [limiter.check("a", 3, 60) for _ in range(3)] == [0, 0, 0]
    assert limiter.check("a", 3, 60) > 0


def test_limiter_reports_the_seconds_until_a_hit_expires():
    clock = FakeClock()
    limiter = RequestRateLimiter(clock=clock)
    limiter.check("a", 1, 60)
    clock.now = 10

    assert limiter.check("a", 1, 60) == 50


def test_limiter_allows_again_once_the_window_has_passed():
    clock = FakeClock()
    limiter = RequestRateLimiter(clock=clock)
    limiter.check("a", 1, 60)
    clock.now = 59.9
    assert limiter.check("a", 1, 60) > 0

    clock.now = 60
    assert limiter.check("a", 1, 60) == 0


def test_limiter_keeps_keys_independent():
    limiter = RequestRateLimiter(clock=FakeClock())
    limiter.check("alice", 1, 60)

    assert limiter.check("bob", 1, 60) == 0


def test_user_limit_returns_429_with_retry_after_and_no_internal_detail(monkeypatch):
    limiter = RequestRateLimiter(clock=FakeClock())
    monkeypatch.setattr(rate_limit_module, "request_limiter", limiter)
    check = rate_limit("probe", 1, 60, key="ip")
    request = make_request()
    check(request)

    with pytest.raises(HTTPException) as caught:
        check(request)

    assert caught.value.status_code == 429
    assert caught.value.headers == {"Retry-After": "60"}
    assert caught.value.detail == "Too many requests, try again later"
