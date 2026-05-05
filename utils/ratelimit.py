"""In-memory sliding-window rate limiter (per-key).

Suitable for the single-process threaded Flask we ship. For a multi-worker
deployment you'd need a shared store (Redis, memcached) — not the case here.

Usage:
    LIMITER = RateLimiter(max_attempts=5, window_seconds=300)

    allowed, retry_in = LIMITER.check(request.remote_addr)
    if not allowed:
        return jsonify({"error": f"Try again in {int(retry_in)}s"}), 429
"""

import threading
import time


class RateLimiter:
    """Per-key sliding-window counter. Thread-safe."""

    def __init__(self, max_attempts: int, window_seconds: int):
        self.max     = max_attempts
        self.window  = window_seconds
        self._lock   = threading.Lock()
        self._buckets: dict[str, list[float]] = {}

    def check(self, key: str) -> tuple[bool, float]:
        """Register an attempt for `key` and report whether it's allowed.

        Returns (allowed, seconds_until_reset). On reject the attempt is
        NOT recorded — only successful checks count toward the limit, so
        an already-blocked attacker can't extend their own ban.
        """
        now    = time.time()
        cutoff = now - self.window
        with self._lock:
            attempts = self._buckets.setdefault(key, [])
            # Drop expired
            attempts[:] = [t for t in attempts if t > cutoff]
            if len(attempts) >= self.max:
                reset_in = attempts[0] + self.window - now
                return False, max(0.0, reset_in)
            attempts.append(now)
            # Periodic GC so abandoned keys don't leak memory
            if len(self._buckets) > 1024:
                self._gc(cutoff)
            return True, 0.0

    def reset(self, key: str) -> None:
        """Clear `key`'s bucket — call after a successful auth."""
        with self._lock:
            self._buckets.pop(key, None)

    def _gc(self, cutoff: float) -> None:
        empty = [k for k, v in self._buckets.items() if not v or v[-1] < cutoff]
        for k in empty:
            del self._buckets[k]


# Shared instances, configured for the auth endpoints.
# /api/login:           5 attempts / 5 min — brute-force window for the 6-digit code
# /api/passkey/auth/*:  10 attempts / 5 min — cryptographic so weaker rate is fine
# /api/passkey/register/begin: 5 attempts / 5 min — protects the setup password

LOGIN_LIMITER         = RateLimiter(max_attempts=5,  window_seconds=300)
PASSKEY_AUTH_LIMITER  = RateLimiter(max_attempts=10, window_seconds=300)
PASSKEY_REG_LIMITER   = RateLimiter(max_attempts=5,  window_seconds=300)
