"""
旧版 ipweb 模块兼容入口。
"""

from .generator.core import DynamicProxyClient, Gateway, PreparedProxy, generate_session_id

__all__ = [
    "DynamicProxyClient",
    "Gateway",
    "PreparedProxy",
    "generate_session_id",
]
