"""Rate limits for the public ask endpoint.

The agent runs on a free-tier key: 8,000 tokens a minute and 200,000 a day. A public URL with
no limit is a way for one stranger with a loop to take the demo offline for everyone until
tomorrow. Two layers: per client, so one visitor cannot starve the rest, and global, so the
whole deployment stays inside the provider's quota. Everything defaults to off; the public
deployment turns it on.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class _Window:
    def __init__(self, limit: int, seconds: int) -> None:
        self.limit = limit
        self.seconds = seconds
        self.hits: deque[float] = deque()

    def wait(self, now: float) -> int:
        """Seconds until one more call is allowed; 0 means allowed now. Does not record."""
        if self.limit <= 0:
            return 0
        while self.hits and now - self.hits[0] >= self.seconds:
            self.hits.popleft()
        if len(self.hits) < self.limit:
            return 0
        return max(1, int(self.seconds - (now - self.hits[0])) + 1)

    def record(self, now: float) -> None:
        if self.limit > 0:
            self.hits.append(now)


class RateLimiter:
    def __init__(self, per_ip_minute: int = 0, per_ip_day: int = 0,
                 global_minute: int = 0, global_day: int = 0, clock=time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._per_ip = (per_ip_minute, per_ip_day)
        self._ip: dict[str, tuple[_Window, _Window]] = defaultdict(
            lambda: (_Window(per_ip_minute, 60), _Window(per_ip_day, 86_400)))
        self._global = (_Window(global_minute, 60), _Window(global_day, 86_400))

    @property
    def enabled(self) -> bool:
        return any(w.limit > 0 for w in self._global) or any(n > 0 for n in self._per_ip)

    def check(self, client: str) -> int:
        """0 and the call is recorded, or the seconds the caller should wait."""
        now = self._clock()
        with self._lock:
            windows = (*self._ip[client or "?"], *self._global)
            wait = max(w.wait(now) for w in windows)
            if wait:
                return wait
            for w in windows:
                w.record(now)
            return 0
