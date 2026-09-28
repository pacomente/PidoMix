"""Limitador simple en memoria (por proceso) para frenar intentos de login por fuerza bruta."""
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, limit: int = 5, window_seconds: int = 300):
        self.limit, self.window = limit, window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)

    def _purge(self, key: str, now: float) -> deque:
        q = self._hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def blocked(self, key: str) -> bool:
        return len(self._purge(key, time.monotonic())) >= self.limit

    def hit(self, key: str) -> None:
        now = time.monotonic()
        self._purge(key, now).append(now)

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)
