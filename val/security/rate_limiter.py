"""
VAL Rate Limiter
================
Shared rate limiter used by BOTH the API server and CLI chat path.

Rules:
  - Per-client (IP for API, "cli" key for terminal)
  - Sliding 60-second window
  - Configurable limit from VAL_RATE_LIMIT in .env (default 30/min)
  - Exceeding the limit raises RateLimitError (caught by callers)
"""

import time
import threading
from typing import Dict, Tuple


class RateLimitError(Exception):
    """Raised when a client exceeds the configured request rate limit."""
    pass


class RateLimiter:
    """
    Thread-safe sliding-window rate limiter.

    Uses a per-client deque of timestamps. Requests older than 60 seconds
    are evicted on each check, so the window slides continuously.

    Args:
        max_per_minute: Maximum allowed requests per 60-second window.
    """

    WINDOW_SECONDS = 60

    def __init__(self, max_per_minute: int):
        self._max = max_per_minute
        self._clients: Dict[str, list] = {}   # client_key → [timestamps]
        self._lock = threading.Lock()

    def check(self, client_key: str = "cli") -> Tuple[bool, int]:
        """
        Check if client_key is within rate limit.

        Returns:
            (allowed: bool, remaining: int)
        """
        now = time.time()
        cutoff = now - self.WINDOW_SECONDS

        with self._lock:
            timestamps = self._clients.get(client_key, [])
            # Evict expired entries (sliding window)
            timestamps = [t for t in timestamps if t > cutoff]
            timestamps.append(now)
            self._clients[client_key] = timestamps
            count = len(timestamps)

        remaining = max(0, self._max - count)
        allowed = count <= self._max
        return allowed, remaining

    def enforce(self, client_key: str = "cli") -> int:
        """
        Check rate limit and raise RateLimitError if exceeded.

        Returns:
            Remaining requests in current window.

        Raises:
            RateLimitError: If the client has exceeded the rate limit.
        """
        allowed, remaining = self.check(client_key)
        if not allowed:
            raise RateLimitError(
                f"Rate limit exceeded ({self._max} requests/min). "
                f"Wait a moment before sending another message."
            )
        return remaining

    def status(self, client_key: str = "cli") -> dict:
        """Return current usage stats for a client."""
        now = time.time()
        cutoff = now - self.WINDOW_SECONDS
        with self._lock:
            timestamps = [t for t in self._clients.get(client_key, []) if t > cutoff]
        return {
            "client": client_key,
            "used": len(timestamps),
            "limit": self._max,
            "remaining": max(0, self._max - len(timestamps)),
            "window_seconds": self.WINDOW_SECONDS,
        }

    def reset(self, client_key: str = "cli") -> None:
        """Clear rate limit state for a client (for testing)."""
        with self._lock:
            self._clients.pop(client_key, None)


# ─── Singleton ──────────────────────────────────────────────────────────────

_limiter: "RateLimiter | None" = None
_limiter_lock = threading.Lock()


def get_rate_limiter() -> RateLimiter:
    """
    Return the singleton RateLimiter.
    Reads VAL_RATE_LIMIT from config on first call.
    """
    global _limiter
    if _limiter is not None:
        return _limiter

    with _limiter_lock:
        if _limiter is not None:
            return _limiter
        from val.config.settings import get_config
        cfg = get_config()
        _limiter = RateLimiter(max_per_minute=cfg.security.rate_limit_per_minute)

    return _limiter
