"""
proxy_scheduler — Direct dynamic-proxy request SDK for IPWeb.

Public surface
──────────────
    ProxySchedulerClient   High-level client (recommended entry point)
    TaskConfig             Per-request configuration
    RequestResult          Request outcome
    TransportBackend       CURL_CFFI | REQUESTS
    RefererMode            SEARCH | SELF | NONE
    RetryConfig            Retry + back-off settings
Typical usage
─────────────
    from proxy_scheduler import ProxySchedulerClient

    with ProxySchedulerClient(user_id="uid", password="pass") as client:
        result = client.get("https://httpbin.org/ip")
        print(result.text)
"""

from .client import ProxySchedulerClient
from .generator import DynamicProxyGenerator
from .ipweb import PreparedProxy
from .core.models import (
    FailureType,
    ProxyStatus,
    RefererMode,
    RequestResult,
    TaskConfig,
    TransportBackend,
)
from .retry.strategy import RetryConfig

__all__ = [
    "DynamicProxyGenerator",
    "FailureType",
    "PreparedProxy",
    "ProxySchedulerClient",
    "ProxyStatus",
    "RefererMode",
    "RequestResult",
    "RetryConfig",
    "TaskConfig",
    "TransportBackend",
]
