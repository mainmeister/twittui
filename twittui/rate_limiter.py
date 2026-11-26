"""Thread-safe sliding-window rate limiter for TWiT REST API calls."""

from __future__ import annotations

from collections import deque
from contextlib import contextmanager
import os
import threading
import time
from typing import Any, Callable, Iterator

import requests

from twittui.logging_config import get_logger

_logger = get_logger("rate_limiter")


class ApiRateLimiter:
    """Limit API request starts across all threads in this process."""

    def __init__(
        self,
        rate_limit: int | Callable[[], int] | None = 5,
        http_get_provider: Callable[[], Callable[..., Any]] | None = None,
    ) -> None:
        self.timestamps: deque[float] = deque()
        self.lock = threading.Lock()
        self.wait_callback: Callable[[bool], Any] | None = None
        self.rate_limit = rate_limit
        self._http_get_provider = http_get_provider
        self._local = threading.local()

    @contextmanager
    def suppress_wait_notifications(self) -> Iterator[None]:
        """Suppress modal wait callbacks on the current thread while preserving rate limiting."""
        prev = getattr(self._local, "suppress_wait", False)
        self._local.suppress_wait = True
        try:
            yield
        finally:
            self._local.suppress_wait = prev

    def _sleep(self, delay: float) -> None:
        time.sleep(delay)

    def _resolve_http_get(self) -> Callable[..., Any]:
        if callable(self._http_get_provider):
            return self._http_get_provider()
        return requests.get

    def get_rate_limit(self) -> int:
        if callable(self.rate_limit):
            try:
                val = int(self.rate_limit())
                return val if val > 0 else 5
            except (ValueError, TypeError):
                _logger.debug("Invalid callable rate_limit result; defaulting to 5", exc_info=True)
                return 5
        if self.rate_limit is not None:
            try:
                val = int(self.rate_limit)
                return val if val > 0 else 5
            except (ValueError, TypeError):
                _logger.debug("Invalid configured rate_limit; checking env vars", exc_info=True)
        env_val = (
            os.getenv("twitapiratelimit")
            or os.getenv("TWITAPIRATELIMIT")
            or os.getenv("twitclubratelimit")
            or os.getenv("TWITCLUBRATELIMIT")
            or os.getenv("TWIT_API_RATE_LIMIT")
        )
        if env_val:
            try:
                val = int(env_val)
                return val if val > 0 else 5
            except ValueError:
                _logger.debug("Invalid env rate limit %r; defaulting to 5", env_val)
        return 5

    def get(self, url: str, **kwargs: Any) -> Any:
        callback = None if getattr(self._local, "suppress_wait", False) else self.wait_callback
        if callback:
            callback(True)
        try:
            return self._get(url, **kwargs)
        finally:
            if callback:
                callback(False)

    def _get(self, url: str, **kwargs: Any) -> Any:
        with self.lock:
            retried = False
            http_get = self._resolve_http_get()
            while True:
                now = time.monotonic()
                while self.timestamps and now - self.timestamps[0] >= 60:
                    self.timestamps.popleft()
                delay = max(0.0, 1.0 - (now - self.timestamps[-1])) if self.timestamps else 0.0
                limit = self.get_rate_limit()
                if len(self.timestamps) >= limit:
                    delay = max(delay, 60.0 - (now - self.timestamps[0]))
                if delay <= 0:
                    self.timestamps.append(now)
                    response = http_get(url, **kwargs)
                    body = getattr(response, "text", "")
                    body_str = body.lower() if isinstance(body, str) else ""
                    reason_str = str(getattr(response, "reason", "")).lower()
                    if (
                        not retried
                        and response.status_code == 500
                        and "usage limits are exceeded" in body_str
                    ):
                        retried = True
                        now_current = time.monotonic()
                        latest_timestamp = self.timestamps[-1] if self.timestamps else now_current
                        wait_time = max(0.0, 10.0 - (now_current - latest_timestamp))
                        self._sleep(wait_time if wait_time > 0 else 10.0)
                        continue
                    if (
                        not retried
                        and response.status_code == 403
                        and (
                            "request blocked" in body_str
                            or "request blocked" in reason_str
                            or "rate limit" in body_str
                            or "usage limit" in body_str
                        )
                    ):
                        retried = True
                        now_current = time.monotonic()
                        latest_timestamp = self.timestamps[-1] if self.timestamps else now_current
                        wait_time = max(0.0, 10.0 - (now_current - latest_timestamp))
                        self._sleep(wait_time if wait_time > 0 else 10.0)
                        continue
                    return response
                self._sleep(delay)
