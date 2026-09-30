from __future__ import annotations

from agent.ratelimit import RateLimiter


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_everything_is_allowed_when_no_limit_is_set():
    rl = RateLimiter()
    assert not rl.enabled
    assert all(rl.check("1.2.3.4") == 0 for _ in range(1000))


def test_the_per_client_limit_does_not_starve_other_clients():
    clock = Clock()
    rl = RateLimiter(per_ip_minute=2, clock=clock)
    assert rl.check("a") == 0 and rl.check("a") == 0
    wait = rl.check("a")
    assert 1 <= wait <= 61
    assert rl.check("b") == 0


def test_the_global_limit_applies_across_clients():
    rl = RateLimiter(global_minute=3, clock=Clock())
    assert [rl.check(ip) for ip in ("a", "b", "c")] == [0, 0, 0]
    assert rl.check("d") > 0


def test_the_window_slides():
    clock = Clock()
    rl = RateLimiter(per_ip_minute=1, clock=clock)
    assert rl.check("a") == 0
    clock.now += 30
    assert rl.check("a") == 31
    clock.now += 30
    assert rl.check("a") == 0


def test_a_rejected_call_does_not_use_up_quota():
    """Otherwise a client retrying in a tight loop would lock itself out indefinitely, and a
    global rejection would still count against the client that was turned away."""
    clock = Clock()
    rl = RateLimiter(per_ip_minute=5, global_minute=1, clock=clock)
    assert rl.check("a") == 0
    for _ in range(20):
        assert rl.check("b") > 0
    clock.now += 60
    assert rl.check("b") == 0


def test_the_daily_limit_holds_after_the_minute_window_resets():
    clock = Clock()
    rl = RateLimiter(per_ip_minute=10, per_ip_day=2, clock=clock)
    assert rl.check("a") == 0 and rl.check("a") == 0
    clock.now += 120
    wait = rl.check("a")
    assert wait > 3600
