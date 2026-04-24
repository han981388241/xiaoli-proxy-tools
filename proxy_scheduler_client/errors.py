"""
proxy_scheduler_client 异常导出入口。
"""

from .client.errors import (
    ClientClosedError,
    ConnectTimeoutError,
    ProtocolError,
    ProxyAuthError,
    ProxyClientError,
    ProxyConnectionError,
    ProxyTimeoutError,
    ReadTimeoutError,
    SessionStateError,
    TargetConnectionError,
    TLSError,
    TotalTimeoutError,
    TransportDependencyMissing,
    TransportError,
)

__all__ = [
    "ClientClosedError",
    "ConnectTimeoutError",
    "ProtocolError",
    "ProxyAuthError",
    "ProxyClientError",
    "ProxyConnectionError",
    "ProxyTimeoutError",
    "ReadTimeoutError",
    "SessionStateError",
    "TargetConnectionError",
    "TLSError",
    "TotalTimeoutError",
    "TransportDependencyMissing",
    "TransportError",
]
