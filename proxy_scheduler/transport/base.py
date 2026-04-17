"""
Abstract transport interface.

All concrete transports must implement ``fetch`` (sync) or ``async_fetch``
(async).  The executor calls the appropriate method based on the backend.

Response contract
─────────────────
Both methods must return an object that exposes:
  .status_code : int
  .text        : str
  .content     : bytes
  .headers     : mapping
  .cookies     : mapping
  .url         : str  (final URL after redirects)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class TransportResponse:
    """
    Thin wrapper so both requests and curl_cffi responses present a
    uniform interface to the executor.
    """

    def __init__(self, raw) -> None:
        self._raw = raw

    @property
    def status_code(self) -> int:
        return self._raw.status_code

    @property
    def text(self) -> str:
        return self._raw.text

    @property
    def content(self) -> bytes:
        return self._raw.content

    @property
    def headers(self) -> dict[str, str]:
        return dict(self._raw.headers)

    @property
    def cookies(self) -> dict[str, str]:
        try:
            return dict(self._raw.cookies)
        except Exception:
            return {}

    @property
    def reason(self) -> str:
        try:
            return str(self._raw.reason)
        except Exception:
            return ""

    @property
    def encoding(self) -> Optional[str]:
        return getattr(self._raw, "encoding", None)

    @property
    def url(self) -> str:
        try:
            return str(self._raw.url)
        except Exception:
            return ""

    def __repr__(self) -> str:
        return f"<TransportResponse status={self.status_code} url={self.url!r}>"


class AbstractTransport(ABC):
    """
    Base class for all HTTP transports.

    Concrete subclasses implement either ``fetch`` (sync) or
    ``async_fetch`` (async) — or both.
    """

    @abstractmethod
    def fetch(
        self,
        method:   str,
        url:      str,
        *,
        headers:  dict[str, str],
        proxies:  dict[str, str],
        params:   Optional[dict]  = None,
        body:     Any             = None,
        timeout:  float           = 30.0,
        proxy_key: str            = "__default__",
    ) -> TransportResponse:
        """Synchronous HTTP request."""
        ...

    async def async_fetch(
        self,
        method:   str,
        url:      str,
        *,
        headers:  dict[str, str],
        proxies:  dict[str, str],
        params:   Optional[dict] = None,
        body:     Any            = None,
        timeout:  float          = 30.0,
        proxy_key: str           = "__default__",
    ) -> TransportResponse:
        """
        Asynchronous HTTP request.

        Default implementation runs ``fetch`` in the executor thread pool
        so that sync-only transports can still be used from async code.
        """
        import asyncio, functools
        loop = asyncio.get_running_loop()
        fn   = functools.partial(
            self.fetch, method, url,
            headers=headers, proxies=proxies,
            params=params, body=body, timeout=timeout,
            proxy_key=proxy_key,
        )
        return await loop.run_in_executor(None, fn)
