"""
Advanced Proxy SDK — complete usage examples.

Covers:
  1. Simple synchronous GET
  2. Synchronous GET with US residential IP
  3. Async single request
  4. Async batch scraping (concurrency-bounded)
  5. Sticky sessions (login flows)
  6. Custom retry config
  7. Raw TaskConfig for full control
  8. Direct proxy mode status
  9. requests backend (no TLS spoofing)

Run this file directly to execute the echo demos (no real scraping target):
    python examples/advanced_proxy_usage.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Make the repo root importable when running from examples/
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from proxy_scheduler import (
    ProxySchedulerClient,
    RequestResult,
    RetryConfig,
    TaskConfig,
    TransportBackend,
    RefererMode,
)

# ── Credentials (replace with your real values) ──────────────────────────
USER_ID  = ""
PASSWORD = ""
GATEWAY  = "apac"           # "americas" | "apac" | "emea"


# =========================================================================
# Helper
# =========================================================================

def print_result(label: str, result: RequestResult) -> None:
    status = "OK" if result.success else "FAIL"
    print(
        f"[{status}] {label} | "
        f"attempts={result.attempts} "
        f"status={result.status_code} "
        f"latency={result.latency_ms:.0f}ms "
        f"session={result.session_id[:8] if result.session_id else 'N/A'}…"
    )
    if result.success and result.body:
        # Print first 200 chars of body
        print(f"       body: {result.text[:200]!r}")
    elif not result.success:
        print(f"       failure: {result.failure_type} / {result.blocked_reason!r}")


# =========================================================================
# 1. Simple synchronous GET — no configuration
# =========================================================================

def demo_simple_get(client: ProxySchedulerClient) -> None:
    print("\n── 1. Simple GET ─────────────────────────────────")
    result = client.get("https://httpbin.org/ip")
    print_result("httpbin /ip", result)


# =========================================================================
# 2. GET with US residential IP
# =========================================================================

def demo_country_targeting(client: ProxySchedulerClient) -> None:
    print("\n── 2. Country-targeted GET (US) ──────────────────")
    result = client.get(
        "https://httpbin.org/ip",
        country_code="US",
    )
    print_result("httpbin /ip (US proxy)", result)


# =========================================================================
# 3. Async single request
# =========================================================================

async def demo_async_get(client: ProxySchedulerClient) -> None:
    print("\n── 3. Async GET ──────────────────────────────────")
    result = await client.async_get(
        "https://httpbin.org/headers",
        headers={"X-Custom-Header": "hello-from-sdk"},
    )
    print_result("httpbin /headers", result)


# =========================================================================
# 4. Batch scraping — multiple URLs concurrently
# =========================================================================

async def demo_batch(client: ProxySchedulerClient) -> None:
    print("\n── 4. Batch scraping (5 tasks, concurrency=3) ────")

    urls = [
        "https://httpbin.org/ip",
        "https://httpbin.org/user-agent",
        "https://httpbin.org/headers",
        "https://httpbin.org/get?page=1",
        "https://httpbin.org/get?page=2",
    ]

    tasks = [
        TaskConfig(url=url, method="GET", max_retries=2)
        for url in urls
    ]

    results = await client.async_batch(tasks, concurrency=3)

    for url, res in zip(urls, results):
        print_result(url.split("/")[-1], res)


# =========================================================================
# 5. Sticky session — simulate logged-in browsing
#    Same proxy IP + same fingerprint across multiple requests
# =========================================================================

async def demo_sticky_session(client: ProxySchedulerClient) -> None:
    print("\n── 5. Sticky session ─────────────────────────────")

    SITE = "httpbin.org"

    # First request — "login"
    r1 = await client.async_post(
        "https://httpbin.org/post",
        body={"username": "alice", "password": "secret"},
        sticky  = True,
        site_id = SITE,
    )
    print_result("POST /login", r1)

    # Second request — "browse" using same IP + session
    r2 = await client.async_get(
        "https://httpbin.org/cookies",
        sticky  = True,
        site_id = SITE,
    )
    print_result("GET /cookies", r2)

    # Verify same session_id was used
    if r1.session_id and r2.session_id:
        same = r1.session_id == r2.session_id
        print(f"       same_proxy_session={same}")


# =========================================================================
# 6. Custom retry configuration
# =========================================================================

def demo_custom_config() -> None:
    print("\n── 6. Custom retry config ───────────────────────")

    custom_client = ProxySchedulerClient(
        user_id  = USER_ID,
        password = PASSWORD,
        gateway  = GATEWAY,

        retry_config=RetryConfig(
            max_retries        = 5,
            base_delay_sec     = 0.5,
            max_delay_sec      = 15.0,
            jitter             = True,
            rate_limit_floor_sec = 3.0,
        ),

        log_level=logging.DEBUG,
    )

    print("custom_client ready:", custom_client.pool_stats())
    custom_client.shutdown()


# =========================================================================
# 7. Raw TaskConfig — full control over every parameter
# =========================================================================

async def demo_raw_task(client: ProxySchedulerClient) -> None:
    print("\n── 7. Raw TaskConfig ─────────────────────────────")

    task = TaskConfig(
        url          = "https://httpbin.org/post",
        method       = "POST",
        headers      = {
            "Content-Type": "application/json",
            "X-Api-Key":    "demo-key-123",
        },
        body         = {"query": "proxy sdk test", "page": 1},
        country_code = "000",        # Any country
        referer_mode = RefererMode.SELF,
        timeout      = 20.0,
        max_retries  = 2,
        backend      = TransportBackend.CURL_CFFI,
        sticky_session = False,
    )

    result = await client.executor.execute(task)
    print_result("POST /post (raw task)", result)


# =========================================================================
# 8. Direct proxy mode status
# =========================================================================

def demo_pool_stats(client: ProxySchedulerClient) -> None:
    print("\n── 8. Client mode ────────────────────────────────")
    stats = client.pool_stats()
    for k, v in stats.items():
        print(f"   {k:15s}: {v}")


# =========================================================================
# 9. Requests backend (sync, no TLS spoofing)
#    Suitable for low-security targets or internal APIs
# =========================================================================

def demo_requests_backend(client: ProxySchedulerClient) -> None:
    print("\n── 9. Requests backend (sync) ────────────────────")

    task = TaskConfig(
        url     = "https://httpbin.org/ip",
        method  = "GET",
        backend = TransportBackend.REQUESTS,
    )
    result = client.executor.execute_sync(task)
    print_result("GET /ip (requests backend)", result)


# =========================================================================
# Main
# =========================================================================

async def run_async_demos(client: ProxySchedulerClient) -> None:
    await demo_async_get(client)
    await demo_batch(client)
    await demo_sticky_session(client)
    await demo_raw_task(client)


def main() -> None:
    # Increase logging verbosity to see scheduler internals
    logging.basicConfig(
        level  = logging.WARNING,
        format = "%(levelname)s %(name)s %(message)s",
    )

    print("=" * 60)
    print("  proxy_scheduler SDK — demo suite")
    print("=" * 60)
    print(f"  user_id={USER_ID!r}  gateway={GATEWAY!r}")

    # Build the shared client (each attempt gets a fresh dynamic proxy)
    with ProxySchedulerClient(
        user_id     = USER_ID,
        password    = PASSWORD,
        gateway     = GATEWAY,
        speed_mode  = True,    # Faster delays for demo; remove for production
        log_level   = logging.INFO,
    ) as client:

        # Sync demos
        demo_simple_get(client)
        demo_country_targeting(client)
        demo_pool_stats(client)
        demo_requests_backend(client)

        # Async demos
        asyncio.run(run_async_demos(client))

        # Custom config demo (creates its own client)
        demo_custom_config()

        # Final client mode
        demo_pool_stats(client)

    print("\nDone.")





if __name__ == "__main__":
    main()
