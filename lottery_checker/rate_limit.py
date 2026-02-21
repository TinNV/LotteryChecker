from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import math
from threading import Lock
from time import monotonic
from typing import Deque, DefaultDict, Tuple


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int = 0


class InMemoryRateLimiter:
    def __init__(
        self,
        *,
        window_seconds: int = 60,
        max_requests_per_window: int = 120,
        max_post_root_requests_per_window: int = 20,
    ) -> None:
        self.window_seconds = max(1, int(window_seconds))
        self.max_requests_per_window = max(1, int(max_requests_per_window))
        self.max_post_root_requests_per_window = max(1, int(max_post_root_requests_per_window))
        self._lock = Lock()
        self._buckets: DefaultDict[Tuple[str, str], Deque[float]] = defaultdict(deque)

    def is_exempt(self, *, path: str) -> bool:
        if path == "/health":
            return True
        return path.startswith("/static/")

    def allow(self, *, ip: str, method: str, path: str, now: float | None = None) -> RateLimitDecision:
        if self.is_exempt(path=path):
            return RateLimitDecision(allowed=True)

        checked_at = float(monotonic() if now is None else now)
        method_value = method.upper().strip()
        ip_value = ip.strip() or "-"
        rules = [(("all", ip_value), self.max_requests_per_window)]
        if method_value == "POST" and path == "/":
            rules.append((("post_root", ip_value), self.max_post_root_requests_per_window))

        with self._lock:
            retry_after = 0
            for key, limit in rules:
                bucket = self._buckets[key]
                self._trim(bucket, checked_at)
                if len(bucket) >= limit:
                    oldest = bucket[0] if bucket else checked_at
                    wait_seconds = max(1, int(math.ceil((oldest + self.window_seconds) - checked_at)))
                    retry_after = max(retry_after, wait_seconds)

            if retry_after > 0:
                return RateLimitDecision(allowed=False, retry_after_seconds=retry_after)

            for key, _ in rules:
                self._buckets[key].append(checked_at)

        return RateLimitDecision(allowed=True)

    def _trim(self, bucket: Deque[float], checked_at: float) -> None:
        min_allowed = checked_at - self.window_seconds
        while bucket and bucket[0] <= min_allowed:
            bucket.popleft()
