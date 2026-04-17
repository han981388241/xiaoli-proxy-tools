"""
AntiBotEngine — request hardening and block detection.

Three responsibilities
──────────────────────
1. Header construction   : Builds a coherent, fingerprint-consistent header
                           set that mimics a real browser for the target URL.
2. Human-behaviour delay : Inserts statistically plausible inter-request
                           delays (first-visit vs. navigation delays differ).
3. Block detection       : Scans the HTTP response for signs of anti-bot
                           intervention (CAPTCHA, Cloudflare challenge, etc.).

TLS fingerprint strategy
────────────────────────
curl_cffi's ``impersonate`` parameter controls the JA3/JA4 fingerprint at
the TLS handshake level.  We rotate the profile per-request from a weighted
pool to avoid presenting a single static fingerprint.

When using the ``requests`` backend (sync) the TLS fingerprint cannot be
spoofed; a warning is logged but execution continues.  For production scraping
of fingerprint-aware targets, always prefer the curl_cffi backend.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Optional

from ..session.manager import BrowserSession
from ..core.models import RefererMode, TaskConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TLS profile pool
# ---------------------------------------------------------------------------

@dataclass
class TLSProfile:
    name:   str          # curl_cffi impersonate value
    weight: int = 1      # Relative sampling weight

_TLS_PROFILES: list[TLSProfile] = [
    # Chrome desktop
    TLSProfile("chrome142",         weight=8),
    TLSProfile("chrome136",         weight=6),
    TLSProfile("chrome133a",        weight=5),
    TLSProfile("chrome131",         weight=5),
    TLSProfile("chrome124",         weight=4),
    TLSProfile("chrome123",         weight=3),
    TLSProfile("chrome120",         weight=2),
    TLSProfile("chrome119",         weight=1),
    TLSProfile("chrome116",         weight=1),
    TLSProfile("chrome110",         weight=1),
    TLSProfile("chrome107",         weight=1),
    TLSProfile("chrome104",         weight=1),
    TLSProfile("chrome101",         weight=1),
    TLSProfile("chrome100",         weight=1),
    TLSProfile("chrome99",          weight=1),

    # Chrome Android
    TLSProfile("chrome131_android", weight=3),
    TLSProfile("chrome99_android",  weight=1),

    # Edge
    TLSProfile("edge101",           weight=2),
    TLSProfile("edge99",            weight=1),

    # Safari macOS
    TLSProfile("safari2601",        weight=5),
    TLSProfile("safari260",         weight=4),
    TLSProfile("safari184",         weight=3),
    TLSProfile("safari180",         weight=2),
    TLSProfile("safari170",         weight=2),
    TLSProfile("safari155",         weight=1),
    TLSProfile("safari153",         weight=1),

    # Safari iOS
    TLSProfile("safari260_ios",     weight=3),
    TLSProfile("safari184_ios",     weight=2),
    TLSProfile("safari180_ios",     weight=2),
    TLSProfile("safari172_ios",     weight=1),

    # Firefox / Tor
    TLSProfile("firefox144",        weight=3),
    TLSProfile("firefox135",        weight=2),
    TLSProfile("firefox133",        weight=1),
    TLSProfile("tor145",            weight=1),
]

_TLS_POPULATION = [p.name for p in _TLS_PROFILES for _ in range(p.weight)]


def sample_tls_profile() -> str:
    return random.choice(_TLS_POPULATION)


# ---------------------------------------------------------------------------
# Block-signal catalogue
# ---------------------------------------------------------------------------

# Each entry: (substring_to_find_in_body, reason_label)
_HTML_BLOCK_SIGNALS: list[tuple[str, str]] = [
    ("api.solvemedia.com",              "captcha_solvemedia"),
    ("recaptcha/api",                    "captcha_recaptcha"),
    ("hcaptcha.com",                     "captcha_hcaptcha"),
    ("cf-browser-verification",          "cloudflare_challenge"),
    ("cloudflare ray id",                "cloudflare_block"),
    ("please enable javascript",         "js_challenge"),
    ("please verify you are human",      "human_verify"),
    ("access denied",                    "access_denied"),
    ("unusual traffic from your",        "google_block"),
    ("robot or automated",               "bot_detection"),
    ("you have been blocked",            "explicit_block"),
    ("security check",                   "security_check"),
    ("rate limit exceeded",              "rate_limit_page"),
    ("too many requests",                "too_many_requests"),
    ("ddos-guard",                       "ddos_guard"),
    ("akamai reference",                 "akamai_block"),
    ("px-captcha",                       "perimeterx_captcha"),
    ("_pxmid",                           "perimeterx_block"),
]

_BLOCK_STATUS_CODES = {403, 407, 429, 503, 530}

_SUSPICIOUSLY_SHORT_THRESHOLD = 500   # bytes; 200 OK but body < 500 bytes


# ---------------------------------------------------------------------------
# Referer pool
# ---------------------------------------------------------------------------

_SEARCH_REFERERS = [
    "https://www.google.com/",
    "https://www.google.com/search?q=",
    "https://www.bing.com/",
    "https://duckduckgo.com/",
    "https://search.yahoo.com/",
]


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

@dataclass
class HumanDelayConfig:
    """Configurable inter-request delay ranges (milliseconds)."""
    first_visit_min_ms:  int = 2000
    first_visit_max_ms:  int = 5000
    navigation_min_ms:   int = 400
    navigation_max_ms:   int = 2500
    fast_min_ms:         int = 100    # Used when speed_mode=True
    fast_max_ms:         int = 400


class AntiBotEngine:
    """
    Hardens outgoing requests and detects incoming blocks.
    """

    def __init__(
        self,
        delay_config: HumanDelayConfig | None = None,
        speed_mode:   bool = False,
    ) -> None:
        """
        Parameters
        ──────────
        delay_config : Custom delay ranges.  Defaults produce human-like
                       timing that passes most behaviour-analysis checks.
        speed_mode   : When True, uses the fast delay range.  Trade-off:
                       lower latency, higher detection risk on strict targets.
        """
        self.delays     = delay_config or HumanDelayConfig()
        self.speed_mode = speed_mode

    # ------------------------------------------------------------------
    # Header construction
    # ------------------------------------------------------------------

    def build_headers(
        self,
        task:    TaskConfig,
        session: BrowserSession,
    ) -> dict[str, str]:
        """
        Assemble a complete, coherent header set for the request.

        Merge order (later entries win):
          fingerprint base → accept → connection → referer → task overrides
        """
        headers: dict[str, str] = {}

        # 1. Browser fingerprint headers
        headers.update(session.fingerprint.to_headers())

        # 2. Standard content-negotiation headers
        headers["Accept"] = (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8,"
            "application/signed-exchange;v=b3;q=0.7"
        )
        headers["Connection"]      = "keep-alive"
        headers["Upgrade-Insecure-Requests"] = "1"

        # 3. Referer strategy
        referer = self._build_referer(task)
        if referer:
            headers["Referer"] = referer

        # 4. Cookie injection
        if session.cookies:
            headers["Cookie"] = "; ".join(
                f"{k}={v}" for k, v in session.cookies.items()
            )
        # 5. Caller-supplied header overrides (highest priority)
        if task.headers:
            headers.update(task.headers)
        return headers

    # ------------------------------------------------------------------
    # Human delay
    # ------------------------------------------------------------------

    async def async_delay(self, *, is_first_visit: bool = False) -> None:
        await asyncio.sleep(self._sample_delay(is_first_visit))

    def sync_delay(self, *, is_first_visit: bool = False) -> None:
        time.sleep(self._sample_delay(is_first_visit))

    def _sample_delay(self, is_first_visit: bool) -> float:
        if self.speed_mode:
            ms = random.randint(self.delays.fast_min_ms, self.delays.fast_max_ms)
        elif is_first_visit:
            ms = random.randint(self.delays.first_visit_min_ms, self.delays.first_visit_max_ms)
        else:
            ms = random.randint(self.delays.navigation_min_ms, self.delays.navigation_max_ms)
        return ms / 1000.0

    # ------------------------------------------------------------------
    # Block detection
    # ------------------------------------------------------------------

    def detect_block(self, response) -> tuple[bool, str]:
        """
        Returns (is_blocked, reason).
        Checks HTTP status code first (fast path), then body content.
        """
        status = response.status_code

        if status in _BLOCK_STATUS_CODES:
            if status == 429:
                return True, "rate_limited_429"
            if status == 407:
                return True, "proxy_auth_407"
            if status == 403:
                # 403 could be a content-level denial — check body too
                body_check = self._scan_body(response)
                return True, body_check or f"http_403"
            return True, f"http_{status}"

        # 200 OK but challenge / block page
        body_reason = self._scan_body(response)
        if body_reason:
            return True, body_reason

        # Suspiciously short response for a 200
        try:
            body_len = len(response.content)
            if body_len < _SUSPICIOUSLY_SHORT_THRESHOLD and status == 200:
                logger.debug(
                    "suspect_short_response status=200 len=%d url=%s",
                    body_len, response.url,
                )
                # Don't hard-block on this alone; return a soft signal
                return False, ""
        except Exception:
            pass

        return False, ""

    # ------------------------------------------------------------------
    # TLS profile sampling
    # ------------------------------------------------------------------

    @staticmethod
    def sample_tls_profile() -> str:
        return sample_tls_profile()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_referer(self, task: TaskConfig) -> str:
        mode = task.referer_mode

        if mode == RefererMode.NONE:
            return ""

        if mode == RefererMode.SELF:
            return task.url

        if task.custom_referer:
            return task.custom_referer

        # RefererMode.SEARCH (default): random search engine
        return random.choice(_SEARCH_REFERERS)

    @staticmethod
    def _scan_body(response) -> str:
        """Return block-reason string if body contains a known block signal, else ''."""
        try:
            text = response.text.lower()
        except Exception:
            return ""

        for signal, reason in _HTML_BLOCK_SIGNALS:
            if signal in text:
                return reason
        return ""
