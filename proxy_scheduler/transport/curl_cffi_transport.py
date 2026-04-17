"""
curl_cffi-based asynchronous transport with TLS fingerprint spoofing.

Why curl_cffi
─────────────
Standard Python TLS stacks present a distinctive JA3/JA4 fingerprint that
is trivially detected by Cloudflare, Akamai, PerimeterX, etc.  curl_cffi
patches the TLS handshake to exactly replicate the fingerprints of real
browsers, making detection at the network layer essentially impossible.

Key features used
─────────────────
- ``impersonate`` param sets the full TLS + HTTP/2 browser profile.
- Async-native; no thread overhead.
- HTTP/2 supported (significant for Cloudflare-protected sites).
- Connection pool reuse per AsyncSession instance.

Profile rotation
────────────────
A new TLS profile is sampled per-request from the weighted pool in
``antibot.engine``.  You can pin a profile per-site by passing
``tls_profile`` explicitly to ``async_fetch``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from .base import AbstractTransport, TransportResponse
from ..antibot.engine import sample_tls_profile

logger = logging.getLogger(__name__)


class CurlCffiTransport(AbstractTransport):
    """
    Async transport backed by ``curl_cffi``.

    A dedicated ``AsyncSession`` is created per request so that the TLS
    profile is applied cleanly.  If you need connection reuse across
    requests to the same host, pass ``reuse_sessions=True`` — sessions
    are then cached per (proxy_key, tls_profile) pair.
    """

    def __init__(
        self,
        default_tls_profile: Optional[str] = None,
        verify_ssl:          bool           = True,
        reuse_sessions:      bool           = False,
    ) -> None:
        self._default_profile = default_tls_profile
        self._verify          = verify_ssl
        self._reuse           = reuse_sessions
        self._session_cache: dict[str, Any] = {}
        self._curl_cffi = self._import_curl_cffi()

    # ------------------------------------------------------------------
    # AbstractTransport
    # ------------------------------------------------------------------

    def fetch(
        self,
        method:   str,
        url:      str,
        *,
        headers:      dict[str, str],
        proxies:      dict[str, str],
        params:       Optional[dict] = None,
        body:         Any            = None,
        timeout:      float          = 30.0,
        tls_profile:  Optional[str]  = None,
        proxy_key:    str            = "__default__",
    ) -> TransportResponse:
        """
        Synchronous wrapper — runs the async version in a new event loop.
        Prefer ``async_fetch`` in async contexts to avoid blocking threads.
        """
        return asyncio.run(
            self.async_fetch(
                method, url,
                headers=headers, proxies=proxies,
                params=params, body=body,
                timeout=timeout, tls_profile=tls_profile,
                proxy_key=proxy_key,
            )
        )

    async def async_fetch(
        self,
        method:   str,
        url:      str,
        *,
        headers:      dict[str, str],
        proxies:      dict[str, str],
        params:       Optional[dict] = None,
        body:         Any            = None,
        timeout:      float          = 30.0,
        tls_profile:  Optional[str]  = None,
        proxy_key:    str            = "__default__",
    ) -> TransportResponse:
        profile = tls_profile or self._default_profile or sample_tls_profile()
        proxy   = proxies.get("https") or proxies.get("http")

        kwargs: dict[str, Any] = {
            "headers":         headers,
            "params":          params,
            "timeout":         timeout,
            "verify":          self._verify,
            "allow_redirects": True,
        }
        if body is not None:
            if isinstance(body, (dict, list)):
                kwargs["json"] = body
            else:
                kwargs["data"] = body

        logger.debug(
            "curl_cffi_fetch %s %s profile=%s proxy_key=%s",
            method, url, profile, proxy_key[:8],
        )

        if self._reuse:
            session = await self._get_cached_session(proxy_key, profile, proxy)
            raw = await session.request(method, url, **kwargs)
        else:
            async with self._curl_cffi.AsyncSession(
                impersonate=profile,
                proxies={"http": proxy, "https": proxy} if proxy else None,
            ) as session:
                raw = await session.request(method, url, **kwargs)

        return TransportResponse(raw)

    # ------------------------------------------------------------------
    # Session cache (reuse_sessions=True)
    # ------------------------------------------------------------------

    async def _get_cached_session(self, proxy_key: str, profile: str, proxy: Optional[str]):
        cache_key = f"{proxy_key}::{profile}"
        if cache_key not in self._session_cache:
            self._session_cache[cache_key] = self._curl_cffi.AsyncSession(
                impersonate=profile,
                proxies={"http": proxy, "https": proxy} if proxy else None,
            )
        return self._session_cache[cache_key]

    async def close_all(self) -> None:
        for session in self._session_cache.values():
            try:
                await session.close()
            except Exception:
                pass
        self._session_cache.clear()

    # ------------------------------------------------------------------
    # Import guard
    # ------------------------------------------------------------------

    @staticmethod
    def _import_curl_cffi():
        try:
            from curl_cffi import requests as curl_requests
            return curl_requests
        except ImportError as exc:
            raise ImportError(
                "curl_cffi is not installed. "
                "Run: pip install curl-cffi"
            ) from exc
