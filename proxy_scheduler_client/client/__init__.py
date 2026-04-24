"""
可选代理请求客户端导出入口。

核心代理生成 SDK 不依赖本模块；只有显式导入本模块时才需要安装请求层可选依赖。
"""

from .client import ProxyClient
from .cluster import ClientCluster, FailurePolicy, RoutingStrategy
from .errors import (
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
from .limits import Limits
from .metrics import ClientMetrics
from .process import ProcessPoolRunner
from .request import RequestSpec
from .response import Response
from .runtime import install_fast_event_loop, recommend_process_count, runtime_snapshot
from .session import CookieRecord, SessionState
from .transport import AiohttpTransport, Transport

__all__ = [
    "AiohttpTransport",
    "ClientCluster",
    "ClientClosedError",
    "ClientMetrics",
    "ConnectTimeoutError",
    "CookieRecord",
    "FailurePolicy",
    "Limits",
    "ProcessPoolRunner",
    "ProtocolError",
    "ProxyAuthError",
    "ProxyClient",
    "ProxyClientError",
    "ProxyConnectionError",
    "ProxyTimeoutError",
    "ReadTimeoutError",
    "RequestSpec",
    "Response",
    "RoutingStrategy",
    "SessionState",
    "SessionStateError",
    "TLSError",
    "TargetConnectionError",
    "TotalTimeoutError",
    "Transport",
    "TransportDependencyMissing",
    "TransportError",
    "install_fast_event_loop",
    "recommend_process_count",
    "runtime_snapshot",
]
