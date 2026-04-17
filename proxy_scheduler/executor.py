"""
RequestExecutor — drives the complete request lifecycle.

Full lifecycle per call to ``execute`` / ``execute_sync``
──────────────────────────────────────────────────────────
  1.  Generate proxy                  Fresh dynamic proxy for this attempt
  2.  SessionManager.get_or_create()  Obtain browser session (fingerprint + cookies)
  3.  AntiBotEngine.build_headers()   Assemble coherent header set
  4.  AntiBotEngine.async_delay()     Human-like inter-request pause
  5.  Transport.async_fetch()         TLS-fingerprinted HTTP request
  6.  AntiBotEngine.detect_block()    Identify block / CAPTCHA responses
  7.  SessionManager.update_cookies() Persist response cookies
  8.  RetryStrategy.should_retry()    Decide whether to loop
  9.  RetryStrategy.needs_new_proxy() Add to blacklist if proxy-level failure
  10. RetryStrategy.async_wait()      Exponential back-off with jitter

Thread / async model
─────────────────────
``execute`` is the primary async entry point; use it from async code.
``execute_sync`` is a convenience wrapper that creates an event loop and
runs ``execute`` inside it — suitable for scripts and notebooks.

For high-throughput batch scraping, use ``execute_many`` which runs a
list of tasks concurrently with a configurable semaphore.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Iterable, Optional

from .antibot.engine import AntiBotEngine, HumanDelayConfig
from .core.models import (
    FailureType,
    ProxyNode,
    RequestResult,
    TaskConfig,
    TransportBackend,
)
from .generator import DynamicProxyGenerator
from .retry.strategy import RetryConfig, RetryStrategy
from .session.manager import SessionManager
from .transport.base import AbstractTransport, TransportResponse
from .transport.curl_cffi_transport import CurlCffiTransport
from .transport.requests_transport import RequestsTransport

logger = logging.getLogger(__name__)


class RequestExecutor:
    """
    Orchestrates all SDK modules for a single request workload.

    Parameters
    ──────────
    proxy_generator : Dynamic proxy generator.
    session_manager : Browser-session / fingerprint store.
    retry_config    : Retry and back-off settings.
    delay_config    : Human-behaviour delay settings.
    speed_mode      : When True, minimal delays (faster but riskier).
    default_backend : Which transport to use when TaskConfig doesn't specify.
    """

    def __init__(
        self,
        proxy_generator: DynamicProxyGenerator | None = None,
        session_manager: SessionManager | None  = None,
        retry_config:    RetryConfig | None     = None,
        delay_config:    HumanDelayConfig | None= None,
        speed_mode:      bool                   = False,
        default_backend: TransportBackend       = TransportBackend.CURL_CFFI,
    ) -> None:
        self.proxy_generator = proxy_generator
        self.sessions    = session_manager or SessionManager()
        self.retry       = RetryStrategy(retry_config)
        self.antibot     = AntiBotEngine(delay_config, speed_mode=speed_mode)
        self._default_be = default_backend

        # Transport instances — lazy-initialised
        self._requests_transport: Optional[RequestsTransport]   = None
        self._curl_transport:     Optional[CurlCffiTransport]   = None

    # ------------------------------------------------------------------
    # Primary async entry point
    # ------------------------------------------------------------------

    async def execute(self, task: TaskConfig) -> RequestResult:
        """
        Execute ``task``, retrying on failure according to RetryConfig.
        Returns a RequestResult regardless of success/failure.
        """
        attempt = 0
        last_result: Optional[RequestResult] = None
        is_first_attempt = True

        while True:
            # ── 1. Generate proxy ──────────────────────────────────────
            proxy = self._get_proxy(task)
            if proxy is None:
                return RequestResult(
                    success       = False,
                    failure_type  = FailureType.CONNECTION_RESET,
                    blocked_reason= "no_proxy_available",
                    attempts      = attempt + 1,
                    task_id       = task.task_id,
                )

            # ── 2. Browser session ────────────────────────────────────
            session = self.sessions.get_or_create(
                proxy_sid    = proxy.session_id,
                site_id      = task.site_id or task.url,
                country_code = proxy.country_code,
                sticky       = task.sticky_session,
            )

            # ── 3. Assemble headers ───────────────────────────────────
            headers = self.antibot.build_headers(task, session)

            # ── 4. Human delay ────────────────────────────────────────
            await self.antibot.async_delay(is_first_visit=is_first_attempt)
            is_first_attempt = False

            # ── 5. Execute HTTP request ────────────────────────────────
            start = time.perf_counter()
            response: Optional[TransportResponse] = None
            exc: Optional[BaseException] = None

            try:
                transport = self._select_transport(task.backend or self._default_be)
                response  = await transport.async_fetch(
                    task.method,
                    task.url,
                    headers   = headers,
                    proxies   = proxy.proxies,
                    params    = task.params,
                    body      = task.body,
                    timeout   = task.timeout,
                    proxy_key = proxy.session_id,
                )
            except Exception as e:
                exc = e
                logger.debug(
                    "transport_error attempt=%d task=%s: %s",
                    attempt, task.task_id, e,
                )

            latency_ms = (time.perf_counter() - start) * 1000.0

            # ── 6. Classify outcome ────────────────────────────────────
            if exc is not None:
                failure_type = self.retry.classify(exception=exc)
                result = RequestResult(
                    success      = False,
                    latency_ms   = latency_ms,
                    session_id   = proxy.session_id,
                    failure_type = failure_type,
                    attempts     = attempt + 1,
                    task_id      = task.task_id,
                )
            else:
                assert response is not None
                is_blocked, block_reason = self.antibot.detect_block(response)

                if is_blocked:
                    failure_type = self.retry.classify(response=response)
                    result = RequestResult(
                        success        = False,
                        status_code    = response.status_code,
                        body           = response.text,
                        content        = response.content,
                        headers        = response.headers,
                        cookies        = response.cookies,
                        url            = response.url,
                        reason         = response.reason,
                        encoding       = response.encoding,
                        latency_ms     = latency_ms,
                        session_id     = proxy.session_id,
                        failure_type   = failure_type,
                        blocked_reason = block_reason,
                        attempts       = attempt + 1,
                        task_id        = task.task_id,
                    )
                else:
                    # Update cookies from successful response
                    self.sessions.update_cookies(
                        session.session_id,
                        response.cookies,
                    )
                    result = RequestResult(
                        success     = True,
                        status_code = response.status_code,
                        body        = response.text,
                        content     = response.content,
                        headers     = response.headers,
                        cookies     = response.cookies,
                        url         = response.url,
                        reason      = response.reason,
                        encoding    = response.encoding,
                        latency_ms  = latency_ms,
                        session_id  = proxy.session_id,
                        attempts    = attempt + 1,
                        task_id     = task.task_id,
                    )

            # ── 7. Return on success ───────────────────────────────────
            if result.success:
                logger.info(
                    "request_success task=%s attempts=%d latency=%.0fms status=%s",
                    task.task_id, result.attempts, result.latency_ms, result.status_code,
                )
                return result

            last_result = result
            failure_type = result.failure_type

            # ── 8. Retry decision ──────────────────────────────────────
            if not self.retry.should_retry(failure_type, attempt, task.max_retries):
                logger.warning(
                    "request_failed task=%s failure=%s attempts=%d (terminal)",
                    task.task_id, failure_type.value, result.attempts,
                )
                return result

            if self.retry.needs_new_proxy(failure_type):
                logger.debug(
                    "proxy_blacklist session=%s failure=%s",
                    proxy.session_id[:8], failure_type.value,
                )
                task.blacklist(proxy.session_id)

            logger.debug(
                "retry attempt=%d/%d task=%s failure=%s",
                attempt + 1, task.max_retries,
                task.task_id, failure_type.value,
            )
            await self.retry.async_wait(attempt, failure_type)
            attempt += 1

        # Should never reach here
        return last_result  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Sync convenience wrapper
    # ------------------------------------------------------------------

    def execute_sync(self, task: TaskConfig) -> RequestResult:
        """
        Run ``execute`` synchronously.

        Safe to call from any non-async context (scripts, tests, CLI).
        Creates a new event loop; do NOT call from inside an existing loop.
        """
        return asyncio.run(self.execute(task))

    # ------------------------------------------------------------------
    # Batch execution
    # ------------------------------------------------------------------

    async def execute_many(
        self,
        tasks:       Iterable[TaskConfig],
        concurrency: int = 10,
    ) -> list[RequestResult]:
        """
        Execute multiple tasks concurrently, bounded by ``concurrency``.

        Returns results in the same order as the input tasks.
        """
        semaphore = asyncio.Semaphore(concurrency)

        async def _guarded(task: TaskConfig) -> RequestResult:
            async with semaphore:
                return await self.execute(task)

        task_list    = list(tasks)
        coroutines   = [_guarded(t) for t in task_list]
        results      = await asyncio.gather(*coroutines, return_exceptions=True)

        # Wrap any unexpected exceptions as failed results
        final: list[RequestResult] = []
        for task, res in zip(task_list, results):
            if isinstance(res, BaseException):
                logger.error("execute_many unhandled exception task=%s: %s", task.task_id, res)
                final.append(RequestResult(
                    success       = False,
                    failure_type  = FailureType.CONNECTION_RESET,
                    blocked_reason= str(res),
                    task_id       = task.task_id,
                ))
            else:
                final.append(res)
        return final

    def execute_many_sync(
        self,
        tasks:       Iterable[TaskConfig],
        concurrency: int = 10,
    ) -> list[RequestResult]:
        return asyncio.run(self.execute_many(tasks, concurrency=concurrency))

    # ------------------------------------------------------------------
    # Transport selection
    # ------------------------------------------------------------------

    def _get_proxy(self, task: TaskConfig) -> ProxyNode | None:
        if self.proxy_generator is None:
            return None

        try:
            return self.proxy_generator.generate_node(
                country_code=task.country_code,
                duration_minutes=task.duration_minutes,
            )
        except Exception as exc:
            logger.error("proxy_generate_error task=%s: %s", task.task_id, exc)
            return None

    def _select_transport(self, backend: TransportBackend) -> AbstractTransport:
        if backend == TransportBackend.REQUESTS:
            if self._requests_transport is None:
                self._requests_transport = RequestsTransport()
            return self._requests_transport
        else:
            if self._curl_transport is None:
                self._curl_transport = CurlCffiTransport()
            return self._curl_transport
