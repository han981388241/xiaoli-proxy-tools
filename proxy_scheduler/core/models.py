"""
Core data models for the proxy scheduler SDK.

All shared enums, dataclasses and result types live here so that
every other module can import from a single, stable source of truth.
"""

from __future__ import annotations

import time
import uuid
from datetime import timedelta
from dataclasses import dataclass, field
from enum import Enum
import json
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class ProxyStatus(Enum):
    HEALTHY   = "healthy"    # Normal operation
    DEGRADED  = "degraded"   # Reserved compatibility status
    OPEN      = "open"       # Circuit open — requests blocked
    HALF_OPEN = "half_open"  # Probe phase — limited requests allowed


class FailureType(Enum):
    # ── Proxy-level failures (switch proxy on retry) ──────────────────────
    PROXY_BANNED      = "proxy_banned"      # 407 / target-site ban
    PROXY_TIMEOUT     = "proxy_timeout"     # Connect/read timeout via proxy
    CONNECTION_RESET  = "connection_reset"  # TCP RST / abrupt close

    # ── Server-level failures (same proxy, back off and retry) ────────────
    RATE_LIMITED      = "rate_limited"      # HTTP 429
    SERVER_ERROR      = "server_error"      # HTTP 5xx

    # ── Terminal failures (do not retry) ─────────────────────────────────
    AUTH_FAILED       = "auth_failed"       # HTTP 403 at content level
    NOT_FOUND         = "not_found"         # HTTP 404
    PARSE_ERROR       = "parse_error"       # Business / parsing error


class RefererMode(Enum):
    SEARCH = "search"   # Random search-engine referer
    SELF   = "self"     # Same URL (intra-site navigation)
    NONE   = "none"     # No Referer header


class TransportBackend(Enum):
    REQUESTS  = "requests"   # Standard requests library (sync)
    CURL_CFFI = "curl_cffi"  # TLS-fingerprint-aware async transport


# ---------------------------------------------------------------------------
# Proxy node — wraps one ipweb session_id (= one residential IP identity)
# ---------------------------------------------------------------------------

@dataclass
class ProxyNode:
    """
    Represents one "IP slot" in the pool.

    In the ipweb model there is a single gateway endpoint; the IP is
    determined by ``session_id`` embedded in the proxy username.  A new
    session_id = a new IP. Circuit-breaker state is tracked per node.
    """

    session_id: str
    proxy_url: str               # http://user:pass@gate:port
    proxies: dict[str, str]      # {"http": ..., "https": ...}
    country_code: str = "000"
    duration_minutes: int = 5

    # Circuit-breaker state
    consecutive_failures: int = 0

    # ── Lifecycle ────────────────────────────────────────────────────────
    status: ProxyStatus = ProxyStatus.HEALTHY
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    last_success: float = field(default_factory=time.time)
    circuit_open_at: Optional[float] = None

    @property
    def key(self) -> str:
        return self.session_id

    def is_usable(self) -> bool:
        return self.status in (
            ProxyStatus.HEALTHY,
            ProxyStatus.DEGRADED,
            ProxyStatus.HALF_OPEN,  # Must be acquirable for circuit-breaker probe
        )

    def __repr__(self) -> str:
        return (
            f"ProxyNode(session={self.session_id[:8]}… "
            f"status={self.status.value})"
        )


# ---------------------------------------------------------------------------
# Task configuration — one logical HTTP request
# ---------------------------------------------------------------------------

@dataclass
class TaskConfig:
    """
    Describes a single scraping task submitted to the executor.
    """

    url: str
    method: str = "GET"
    headers: dict[str, str] = field(default_factory=dict)
    params: Optional[dict[str, Any]] = None
    body: Optional[Any] = None                        # JSON-serialisable or str

    # ── Proxy selection hints ────────────────────────────────────────────
    country_code: str = "000"                         # "000" = any country
    duration_minutes: int = 5
    sticky_session: bool = False                      # Reuse same IP across calls
    site_id: str = ""                                 # Logical site key for stickiness

    # ── Anti-bot hints ───────────────────────────────────────────────────
    referer_mode: RefererMode = RefererMode.SEARCH
    custom_referer: str = ""

    # ── Retry / circuit control ──────────────────────────────────────────
    max_retries: int = 3
    timeout: float = 30.0
    blacklisted_sessions: set[str] = field(default_factory=set)

    # ── Transport ────────────────────────────────────────────────────────
    backend: TransportBackend = TransportBackend.CURL_CFFI

    # ── Internal ─────────────────────────────────────────────────────────
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def blacklist(self, session_id: str) -> None:
        self.blacklisted_sessions.add(session_id)


# ---------------------------------------------------------------------------
# Request result
# ---------------------------------------------------------------------------

@dataclass
class RequestResult:
    """
    Outcome of a single HTTP request after all retries.

    The scheduler keeps proxy-specific metadata on this object, but the
    common response fields intentionally mirror ``requests.Response`` so
    callers can use familiar access patterns such as ``response.text``,
    ``response.content``, ``response.json()`` and ``response.ok``.
    """

    success: bool
    status_code: Optional[int] = None
    body: Optional[str] = None
    content: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    url: str = ""
    reason: str = ""
    encoding: Optional[str] = None
    latency_ms: float = 0.0
    session_id: Optional[str] = None
    failure_type: Optional[FailureType] = None
    blocked_reason: str = ""
    attempts: int = 0
    task_id: str = ""

    @property
    def text(self) -> str:
        if self.body is not None:
            return self.body
        if not self.content:
            return ""
        encoding = self.encoding or "utf-8"
        return self.content.decode(encoding, errors="replace")

    @property
    def ok(self) -> bool:
        return self.status_code is not None and self.status_code < 400

    @property
    def elapsed(self) -> timedelta:
        return timedelta(milliseconds=self.latency_ms)

    @property
    def is_redirect(self) -> bool:
        return self.status_code in (301, 302, 303, 307, 308) and "Location" in self.headers

    @property
    def is_permanent_redirect(self) -> bool:
        return self.status_code in (301, 308) and "Location" in self.headers

    def json(self, **kwargs: Any) -> Any:
        return json.loads(self.text, **kwargs)

    def raise_for_status(self) -> None:
        if self.status_code is None or self.status_code < 400:
            return

        message = f"{self.status_code} Error"
        if self.reason:
            message += f": {self.reason}"
        if self.url:
            message += f" for url: {self.url}"

        try:
            from requests.exceptions import HTTPError
            raise HTTPError(message)
        except ImportError as exc:
            raise RuntimeError(message) from exc

    def raise_for_failure(self) -> None:
        if not self.success:
            raise RuntimeError(
                f"Request failed after {self.attempts} attempt(s): "
                f"{self.failure_type} / {self.blocked_reason}"
            )

    def __bool__(self) -> bool:
        return self.ok
