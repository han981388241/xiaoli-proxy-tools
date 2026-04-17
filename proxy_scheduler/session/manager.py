"""
SessionManager — browser-fingerprint and cookie isolation.

Design
──────
Each (proxy_session_id, site_id) pair gets its own BrowserSession which
carries a consistent fingerprint (UA, language, headers) and an evolving
cookie jar.

Cookie isolation rule
─────────────────────
Cookies are bound to a session.  A session is bound to a single proxy
session_id.  If the proxy changes, the old cookies are NOT carried over,
which prevents the target site from correlating the new IP with the old
session.

Fingerprint generation
──────────────────────
Fingerprints are generated from a curated pool that matches real-world
browser distributions (Chrome ~65 %, Safari ~19 %, Firefox ~4 %).
The pool is seeded from the proxy country so that the Accept-Language and
timezone are geographically plausible.
"""

from __future__ import annotations

import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Fingerprint data pool
# ---------------------------------------------------------------------------

_CHROME_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

_SAFARI_UAS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1",
]

_FIREFOX_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:125.0) Gecko/20100101 Firefox/125.0",
]

# Weighted pool: ~65 % Chrome, ~19 % Safari, ~4 % Firefox, random the rest
_UA_POOL = (
    _CHROME_UAS * 13
    + _SAFARI_UAS * 4
    + _FIREFOX_UAS * 1
)

# Country → (Accept-Language, IANA timezone)
_COUNTRY_LOCALE: dict[str, tuple[str, str]] = {
    "US": ("en-US,en;q=0.9",                       "America/New_York"),
    "GB": ("en-GB,en;q=0.9",                       "Europe/London"),
    "CA": ("en-CA,en;q=0.9,fr-CA;q=0.8",          "America/Toronto"),
    "AU": ("en-AU,en;q=0.9",                       "Australia/Sydney"),
    "DE": ("de-DE,de;q=0.9,en;q=0.8",             "Europe/Berlin"),
    "FR": ("fr-FR,fr;q=0.9,en;q=0.8",             "Europe/Paris"),
    "JP": ("ja-JP,ja;q=0.9,en;q=0.8",             "Asia/Tokyo"),
    "CN": ("zh-CN,zh;q=0.9,en;q=0.8",             "Asia/Shanghai"),
    "KR": ("ko-KR,ko;q=0.9,en;q=0.8",             "Asia/Seoul"),
    "BR": ("pt-BR,pt;q=0.9,en;q=0.8",             "America/Sao_Paulo"),
    "IN": ("en-IN,en;q=0.9,hi;q=0.8",             "Asia/Kolkata"),
    "SG": ("en-SG,en;q=0.9,zh-SG;q=0.8",         "Asia/Singapore"),
    "000": ("en-US,en;q=0.9",                      "America/New_York"),  # fallback
}

_VIEWPORTS = [(1920, 1080), (1440, 900), (1366, 768), (1280, 800), (2560, 1440)]

_SEC_CH_UA_VERSIONS = [
    '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    '"Chromium";v="123", "Google Chrome";v="123", "Not-A.Brand";v="99"',
]


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class BrowserFingerprint:
    user_agent:        str
    accept_language:   str
    accept_encoding:   str
    sec_ch_ua:         str
    sec_ch_ua_platform:str
    sec_ch_ua_mobile:  str
    timezone:          str
    viewport:          tuple[int, int]

    def to_headers(self) -> dict[str, str]:
        """Return headers that should be present on every request."""
        headers = {
            "User-Agent":      self.user_agent,
            "Accept-Language": self.accept_language,
            "Accept-Encoding": self.accept_encoding,
        }
        # sec-ch-ua headers are Chrome-only; Safari and Firefox don't send
        # them, and an empty value is more suspicious than omitting them.
        if self.sec_ch_ua:
            headers["sec-ch-ua"]          = self.sec_ch_ua
            headers["sec-ch-ua-platform"] = f'"{self.sec_ch_ua_platform}"'
            headers["sec-ch-ua-mobile"]   = self.sec_ch_ua_mobile
        return headers


@dataclass
class BrowserSession:
    """
    One isolated browser identity tied to a specific proxy session_id.
    """

    session_id:    str                          # Unique ID for this browser session
    proxy_sid:     str                          # The proxy session_id it is bound to
    site_id:       str
    fingerprint:   BrowserFingerprint
    cookies:       dict[str, str] = field(default_factory=dict)
    request_count: int            = 0
    max_requests:  int            = 50          # Rotate fingerprint after this many
    created_at:    float          = field(default_factory=time.time)

    def is_expired(self) -> bool:
        return self.request_count >= self.max_requests


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

class FingerprintFactory:
    """Generates realistic, geo-consistent browser fingerprints."""

    def generate(self, country_code: str = "000") -> BrowserFingerprint:
        lang, tz = _COUNTRY_LOCALE.get(country_code, _COUNTRY_LOCALE["000"])
        ua       = random.choice(_UA_POOL)

        is_mobile = "iPhone" in ua or "Android" in ua
        platform  = "macOS" if "Macintosh" in ua else ("Windows" if "Windows" in ua else "Linux")
        sec_ch_ua = random.choice(_SEC_CH_UA_VERSIONS) if "Chrome" in ua else ""

        return BrowserFingerprint(
            user_agent        = ua,
            accept_language   = lang,
            accept_encoding   = "gzip, deflate, br, zstd",
            sec_ch_ua         = sec_ch_ua,
            sec_ch_ua_platform= platform,
            sec_ch_ua_mobile  = "?1" if is_mobile else "?0",
            timezone          = tz,
            viewport          = random.choice(_VIEWPORTS),
        )


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

_SESSION_TTL_SEC = 3600  # Evict sticky sessions unused for > 1 hour


class SessionManager:
    """
    Creates and caches BrowserSession objects.

    Key invariant: a BrowserSession is NEVER shared across different
    proxy session_ids.  When the proxy changes, the browser session is
    recreated from scratch (no cookie leakage).

    Only sticky sessions are cached.  Non-sticky requests get a fresh,
    ephemeral session every time and are never stored, preventing
    unbounded memory growth.
    """

    def __init__(self, factory: FingerprintFactory | None = None) -> None:
        self._factory  = factory or FingerprintFactory()
        self._sessions: dict[str, BrowserSession] = {}
        self._lock     = threading.Lock()

    # ------------------------------------------------------------------
    # Acquire
    # ------------------------------------------------------------------

    def get_or_create(
        self,
        *,
        proxy_sid:    str,
        site_id:      str,
        country_code: str  = "000",
        sticky:       bool = False,
    ) -> BrowserSession:
        """
        Return a BrowserSession for the given proxy+site combination.

        sticky=True  → reuse the same session across calls (e.g. logged-in flows).
        sticky=False → new session each time (maximum isolation).

        The returned session's ``session_id`` is always a stable key that
        can be passed to ``update_cookies`` / ``get_cookies``.
        """
        # Non-sticky: return a fresh ephemeral session (never cached)
        if not sticky:
            return BrowserSession(
                session_id  = uuid.uuid4().hex[:12],
                proxy_sid   = proxy_sid,
                site_id     = site_id,
                fingerprint = self._factory.generate(country_code),
                request_count = 1,
            )

        # Sticky: cache keyed by proxy+site
        cache_key = f"{proxy_sid}::{site_id}"

        with self._lock:
            # Periodic eviction of stale sticky sessions
            self._evict_stale()

            session = self._sessions.get(cache_key)

            # Evict if expired or bound to a different proxy
            if session and (session.is_expired() or session.proxy_sid != proxy_sid):
                del self._sessions[cache_key]
                session = None

            if session is None:
                # Use cache_key as session_id so callers can look up cookies
                # by the same key returned in the session object.
                session = BrowserSession(
                    session_id  = cache_key,
                    proxy_sid   = proxy_sid,
                    site_id     = site_id,
                    fingerprint = self._factory.generate(country_code),
                )
                self._sessions[cache_key] = session

            session.request_count += 1
            return session

    # ------------------------------------------------------------------
    # Cookie management
    # ------------------------------------------------------------------

    def update_cookies(
        self,
        cache_key: str,
        cookies:   dict[str, str],
    ) -> None:
        with self._lock:
            if s := self._sessions.get(cache_key):
                s.cookies.update(cookies)

    def get_cookies(self, cache_key: str) -> dict[str, str]:
        with self._lock:
            if s := self._sessions.get(cache_key):
                return dict(s.cookies)
            return {}

    # ------------------------------------------------------------------
    # Housekeeping
    # ------------------------------------------------------------------

    def _evict_stale(self) -> None:
        """Remove sticky sessions that haven't been used for > TTL. Must hold lock."""
        now = time.time()
        stale = [
            k for k, s in self._sessions.items()
            if (now - s.created_at) > _SESSION_TTL_SEC
        ]
        for k in stale:
            del self._sessions[k]

    def purge_for_proxy(self, proxy_sid: str) -> int:
        """Remove all sessions associated with a given proxy session_id."""
        with self._lock:
            before = len(self._sessions)
            self._sessions = {
                k: v for k, v in self._sessions.items()
                if v.proxy_sid != proxy_sid
            }
            return before - len(self._sessions)

    def size(self) -> int:
        with self._lock:
            return len(self._sessions)
