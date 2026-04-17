"""
RetryStrategy — failure classification and back-off logic.

Failure taxonomy
────────────────
                      │ Switch proxy? │ Retry? │
──────────────────────┼───────────────┼────────┤
PROXY_BANNED          │     Yes       │  Yes   │
PROXY_TIMEOUT         │     Yes       │  Yes   │
CONNECTION_RESET      │     Yes       │  Yes   │
RATE_LIMITED          │     No        │  Yes   │  (same proxy, back off)
SERVER_ERROR          │     No        │  Yes   │
AUTH_FAILED           │     No        │  No    │  terminal
NOT_FOUND             │     No        │  No    │  terminal
PARSE_ERROR           │     No        │  No    │  terminal

Back-off formula
────────────────
  delay = min(base * 2^attempt, max_delay) * jitter_factor

  jitter_factor = uniform(0.5, 1.5) when jitter=True
  RATE_LIMITED uses max(computed_delay, rate_limit_floor_sec)
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field

from ..core.models import FailureType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class RetryConfig:
    max_retries:           int   = 3
    base_delay_sec:        float = 1.0
    max_delay_sec:         float = 30.0
    jitter:                bool  = True
    rate_limit_floor_sec:  float = 5.0    # Minimum wait after 429

    # Failure types that require a new proxy on retry
    proxy_swap_on: frozenset[FailureType] = field(
        default_factory=lambda: frozenset({
            FailureType.PROXY_BANNED,
            FailureType.PROXY_TIMEOUT,
            FailureType.CONNECTION_RESET,
        })
    )

    # Failure types that are terminal (never retry)
    terminal: frozenset[FailureType] = field(
        default_factory=lambda: frozenset({
            FailureType.AUTH_FAILED,
            FailureType.NOT_FOUND,
            FailureType.PARSE_ERROR,
        })
    )


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

def classify_response(response=None, exception: BaseException | None = None) -> FailureType:
    """
    Map an HTTP response or exception to a FailureType.

    Priority: exception > HTTP status code > default.
    """
    if exception is not None:
        name = type(exception).__name__.lower()

        # requests / httpx / curl_cffi exception names
        if "proxye" in name:          return FailureType.PROXY_BANNED
        if "timeout" in name:         return FailureType.PROXY_TIMEOUT
        if "connection" in name:      return FailureType.CONNECTION_RESET
        if "reset" in name:           return FailureType.CONNECTION_RESET
        if "ssl" in name:             return FailureType.CONNECTION_RESET
        # Generic network error
        return FailureType.CONNECTION_RESET

    if response is not None:
        status = response.status_code

        if status == 407:             return FailureType.PROXY_BANNED
        if status == 429:             return FailureType.RATE_LIMITED
        if status == 403:             return FailureType.AUTH_FAILED
        if status == 404:             return FailureType.NOT_FOUND
        if status in (401, 405, 406): return FailureType.AUTH_FAILED
        if 500 <= status < 600:       return FailureType.SERVER_ERROR

    return FailureType.CONNECTION_RESET


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------

class RetryStrategy:
    """
    Stateless strategy object; holds configuration and provides decision methods.
    All state (attempt counter) lives in the caller (RequestExecutor).
    """

    def __init__(self, config: RetryConfig | None = None) -> None:
        self.cfg = config or RetryConfig()

    # ------------------------------------------------------------------
    # Decision methods
    # ------------------------------------------------------------------

    def should_retry(
        self,
        failure: FailureType,
        attempt: int,
        max_retries: int | None = None,
    ) -> bool:
        """Return True if the request should be retried."""
        if failure in self.cfg.terminal:
            return False
        limit = self.cfg.max_retries if max_retries is None else max_retries
        return attempt < limit

    def needs_new_proxy(self, failure: FailureType) -> bool:
        """Return True if we must switch to a different proxy before retrying."""
        return failure in self.cfg.proxy_swap_on

    def classify(
        self,
        response=None,
        exception: BaseException | None = None,
    ) -> FailureType:
        return classify_response(response, exception)

    # ------------------------------------------------------------------
    # Back-off
    # ------------------------------------------------------------------

    async def async_wait(self, attempt: int, failure: FailureType) -> None:
        delay = self._compute_delay(attempt, failure)
        logger.debug("retry_backoff attempt=%d delay=%.2fs failure=%s", attempt, delay, failure.value)
        await asyncio.sleep(delay)

    def sync_wait(self, attempt: int, failure: FailureType) -> None:
        import time
        delay = self._compute_delay(attempt, failure)
        logger.debug("retry_backoff attempt=%d delay=%.2fs failure=%s", attempt, delay, failure.value)
        time.sleep(delay)

    def _compute_delay(self, attempt: int, failure: FailureType) -> float:
        delay = min(
            self.cfg.base_delay_sec * (2 ** attempt),
            self.cfg.max_delay_sec,
        )
        if self.cfg.jitter:
            delay *= random.uniform(0.5, 1.5)

        # Enforce floor for rate-limit responses
        if failure == FailureType.RATE_LIMITED:
            delay = max(delay, self.cfg.rate_limit_floor_sec)

        return delay
