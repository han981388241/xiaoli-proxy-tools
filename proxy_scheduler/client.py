"""
ProxySchedulerClient — the single public entry point for the SDK.

Quick start
───────────
    from proxy_scheduler import ProxySchedulerClient, TaskConfig

    client = ProxySchedulerClient(
        user_id="your_uid",
        password="your_pass",
        gateway="apac",
    )

    result = client.get("https://httpbin.org/ip")
    print(result.text)

The client wraps DynamicProxyGenerator, SessionManager, RetryStrategy,
and RequestExecutor under a single coherent surface so callers never
need to wire the components together manually.

Advanced users can access the underlying components directly:
    client.proxy_generator
    client.executor   # RequestExecutor
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from .ipweb import DynamicProxyClient, Gateway
from .generator import DynamicProxyGenerator
from .core.models import (
    RequestResult,
    TaskConfig,
    TransportBackend,
)
from .executor import RequestExecutor
from .retry.strategy import RetryConfig
from .session.manager import SessionManager

logger = logging.getLogger(__name__)


class ProxySchedulerClient:
    """
    High-level facade over the direct dynamic-proxy request stack.

    Parameters
    ──────────
    user_id           : ipweb account user ID.
    password          : ipweb account password.
    gateway           : ipweb gateway — 'americas', 'apac', 'emea', or full hostname.
    default_backend   : HTTP transport — CURL_CFFI (recommended) or REQUESTS.
    speed_mode        : Minimal delays; faster but higher detection risk.
    retry_config      : Custom retry settings.
    log_level         : Python logging level for SDK internals.
    """

    def __init__(
        self,
        *,
        user_id:         str,
        password:        str,
        gateway:         str           = "apac",
        default_backend:  TransportBackend = TransportBackend.CURL_CFFI,
        speed_mode:       bool          = False,
        retry_config:     Optional[RetryConfig]           = None,
        log_level:        int           = logging.WARNING,
    ) -> None:
        logging.getLogger("proxy_scheduler").setLevel(log_level)
        self._default_backend = default_backend

        # Build the ipweb underlying client
        self._ipweb = DynamicProxyClient(
            user_id   = user_id,
            password  = password,
            gateway   = Gateway.normalize(gateway),
        )
        self.proxy_generator = DynamicProxyGenerator(
            user_id=user_id,
            password=password,
            gateway=gateway,
            client=self._ipweb,
        )
        self._sessions = SessionManager()

        self.executor = RequestExecutor(
            proxy_generator = self.proxy_generator,
            session_manager = self._sessions,
            retry_config    = retry_config,
            speed_mode      = speed_mode,
            default_backend = default_backend,
        )

        logger.info(
            "ProxySchedulerClient ready proxy_mode=direct backend=%s",
            default_backend.value,
        )

    # ------------------------------------------------------------------
    # Convenience methods (sync)
    # ------------------------------------------------------------------

    def get(
        self,
        url:              str,
        *,
        params:           Optional[dict[str, Any]] = None,
        headers:          Optional[dict[str, str]] = None,
        country_code:     str  = "000",
        sticky:           bool = False,
        site_id:          str  = "",
        timeout:          float = 30.0,
        max_retries:      int   = 3,
    ) -> RequestResult:
        """Synchronous GET request through a fresh dynamic proxy."""
        return self.executor.execute_sync(
            self._build_task(
                "GET", url,
                params=params, headers=headers,
                country_code=country_code, sticky=sticky,
                site_id=site_id, timeout=timeout,
                max_retries=max_retries,
            )
        )

    def post(
        self,
        url:          str,
        *,
        body:         Any                     = None,
        headers:      Optional[dict[str, str]]= None,
        country_code: str  = "000",
        sticky:       bool = False,
        site_id:      str  = "",
        timeout:      float = 30.0,
        max_retries:  int   = 3,
    ) -> RequestResult:
        """Synchronous POST request through a fresh dynamic proxy."""
        return self.executor.execute_sync(
            self._build_task(
                "POST", url,
                body=body, headers=headers,
                country_code=country_code, sticky=sticky,
                site_id=site_id, timeout=timeout,
                max_retries=max_retries,
            )
        )

    # ------------------------------------------------------------------
    # Async methods
    # ------------------------------------------------------------------

    async def async_get(
        self,
        url:          str,
        *,
        params:       Optional[dict[str, Any]] = None,
        headers:      Optional[dict[str, str]] = None,
        country_code: str   = "000",
        sticky:       bool  = False,
        site_id:      str   = "",
        timeout:      float = 30.0,
        max_retries:  int   = 3,
    ) -> RequestResult:
        return await self.executor.execute(
            self._build_task(
                "GET", url,
                params=params, headers=headers,
                country_code=country_code, sticky=sticky,
                site_id=site_id, timeout=timeout,
                max_retries=max_retries,
            )
        )

    async def async_post(
        self,
        url:          str,
        *,
        body:         Any                      = None,
        headers:      Optional[dict[str, str]] = None,
        country_code: str   = "000",
        sticky:       bool  = False,
        site_id:      str   = "",
        timeout:      float = 30.0,
        max_retries:  int   = 3,
    ) -> RequestResult:
        return await self.executor.execute(
            self._build_task(
                "POST", url,
                body=body, headers=headers,
                country_code=country_code, sticky=sticky,
                site_id=site_id, timeout=timeout,
                max_retries=max_retries,
            )
        )

    # ------------------------------------------------------------------
    # Batch (async)
    # ------------------------------------------------------------------

    async def async_batch(
        self,
        tasks:       list[TaskConfig],
        concurrency: int = 10,
    ) -> list[RequestResult]:
        """Execute a list of TaskConfig objects concurrently."""
        return await self.executor.execute_many(tasks, concurrency=concurrency)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def pool_stats(self) -> dict:
        """Return current client mode information."""
        return {"enabled": False, "mode": "direct_dynamic_proxy"}

    # ------------------------------------------------------------------
    # Dynamic proxy generation channel
    # ------------------------------------------------------------------

    def generate_proxy(
        self,
        *,
        country_code: str = "000",
        duration_minutes: int = 5,
        session_id: str | None = None,
        state_code: str = "",
        city_code: str = "",
    ):
        """Generate one fresh proxy without acquiring it from the pool."""

        return self.proxy_generator.generate(
            country_code=country_code,
            duration_minutes=duration_minutes,
            session_id=session_id,
            state_code=state_code,
            city_code=city_code,
        )

    def generate_proxies(
        self,
        count: int,
        *,
        country_code: str = "000",
        duration_minutes: int = 5,
        state_code: str = "",
        city_code: str = "",
    ):
        """Generate multiple fresh proxies without touching scheduler state."""

        return self.proxy_generator.generate_many(
            count,
            country_code=country_code,
            duration_minutes=duration_minutes,
            state_code=state_code,
            city_code=city_code,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """No-op kept for compatibility."""
        return None

    def __enter__(self) -> "ProxySchedulerClient":
        return self

    def __exit__(self, *_) -> None:
        self.shutdown()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_task(
        self,
        method:       str,
        url:          str,
        *,
        params:       Optional[dict]           = None,
        body:         Any                      = None,
        headers:      Optional[dict[str, str]] = None,
        country_code: str   = "000",
        sticky:       bool  = False,
        site_id:      str   = "",
        timeout:      float = 30.0,
        max_retries:  int   = 3,
    ) -> TaskConfig:
        return TaskConfig(
            url            = url,
            method         = method,
            headers        = headers or {},
            params         = params,
            body           = body,
            country_code   = country_code,
            sticky_session = sticky,
            site_id        = site_id,
            timeout        = timeout,
            max_retries    = max_retries,
            backend        = self._default_backend,
        )
