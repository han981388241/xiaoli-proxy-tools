"""
requests-based synchronous transport.

Limitations vs. curl_cffi
──────────────────────────
- TLS fingerprint is fixed (Python's ssl + urllib3 stack); JA3 is detectable.
- No HTTP/2 by default (requires httpx or hyper).
- Recommended only for targets without fingerprint-level bot detection.

Usage note
──────────
A ``requests.Session`` is created per ProxyNode key so that the underlying
TCP connection pool is reused across requests to the same proxy, reducing
handshake overhead.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Optional

from .base import AbstractTransport, TransportResponse

logger = logging.getLogger(__name__)


class RequestsTransport(AbstractTransport):
    """
    Synchronous transport backed by the ``requests`` library.

    One ``requests.Session`` is kept alive per proxy key (session_id) to
    benefit from connection keep-alive without leaking cookies across proxies.
    """

    def __init__(self, verify_ssl: bool = True) -> None:
        self._verify_ssl = verify_ssl
        self._sessions: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._requests = self._import_requests()

    # ------------------------------------------------------------------
    # AbstractTransport
    # ------------------------------------------------------------------

    def fetch(
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
        session = self._get_session(proxy_key, proxies)

        kwargs: dict[str, Any] = {
            "headers": headers,
            "params":  params,
            "timeout": timeout,
            "verify":  self._verify_ssl,
            "allow_redirects": True,
        }
        if body is not None:
            if isinstance(body, (dict, list)):
                kwargs["json"] = body
            else:
                kwargs["data"] = body

        logger.debug("requests_fetch %s %s via proxy_key=%s", method, url, proxy_key[:8])
        raw = session.request(method, url, **kwargs)
        return TransportResponse(raw)

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def _get_session(self, proxy_key: str, proxies: dict[str, str]) -> Any:
        """Return (or create) a session pinned to a proxy key."""
        with self._lock:
            if proxy_key not in self._sessions:
                session = self._requests.Session()
                session.proxies.update(proxies)
                session.trust_env = False
                self._sessions[proxy_key] = session
            return self._sessions[proxy_key]

    def close_session(self, proxy_key: str) -> None:
        with self._lock:
            if session := self._sessions.pop(proxy_key, None):
                session.close()

    def close_all(self) -> None:
        with self._lock:
            for session in self._sessions.values():
                try:
                    session.close()
                except Exception:
                    pass
            self._sessions.clear()

    # ------------------------------------------------------------------
    # Import guard
    # ------------------------------------------------------------------

    @staticmethod
    def _import_requests():
        try:
            import requests
            return requests
        except ImportError as exc:
            raise ImportError(
                "requests is not installed. "
                "Run: pip install requests"
            ) from exc
