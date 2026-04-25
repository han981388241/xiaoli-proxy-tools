"""
aiohttp 连接池构造工具。
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit
from typing import Any

from .errors import TransportDependencyMissing
from .limits import Limits


_AIOHTTP: Any | None = None


def load_aiohttp() -> Any:
    """
    延迟加载 aiohttp。

    Returns:
        Any: aiohttp 模块。

    Raises:
        TransportDependencyMissing: 缺少 aiohttp 时抛出。
    """

    global _AIOHTTP
    if _AIOHTTP is not None:
        return _AIOHTTP

    try:
        import aiohttp
    except ImportError as exc:
        raise TransportDependencyMissing(
            "http",
            "aiohttp",
            "pip install ipweb-proxy-sdk[client]",
        ) from exc
    _AIOHTTP = aiohttp
    return _AIOHTTP


def build_connector(proxy_url: str, limits: Limits) -> tuple[Any, str | None]:
    """
    根据代理协议构造连接器和 aiohttp 原生代理参数。

    Args:
        proxy_url (str): 代理地址。
        limits (Limits): 运行限制。

    Returns:
        tuple[Any, str | None]: aiohttp 连接器和请求级代理地址。

    Raises:
        TransportDependencyMissing: SOCKS 依赖缺失时抛出。
        ValueError: 代理协议不支持时抛出。
    """

    aiohttp = load_aiohttp()
    normalized_proxy_url, scheme = _normalize_proxy_url_for_connector(proxy_url)

    if scheme in ("http", "https"):
        connector = aiohttp.TCPConnector(
            limit=limits.connector_limit,
            limit_per_host=limits.connector_limit_per_host,
            keepalive_timeout=limits.keepalive_timeout,
            ttl_dns_cache=limits.dns_cache_ttl,
            force_close=False,
        )
        return connector, normalized_proxy_url

    if scheme in ("socks5", "socks5h"):
        try:
            from aiohttp_socks import ProxyConnector
        except ImportError as exc:
            raise TransportDependencyMissing(
                scheme,
                "aiohttp-socks",
                "pip install ipweb-proxy-sdk[socks]",
            ) from exc
        connector = ProxyConnector.from_url(
            normalized_proxy_url,
            rdns=(scheme == "socks5h"),
            limit=limits.connector_limit,
            limit_per_host=limits.connector_limit_per_host,
            keepalive_timeout=limits.keepalive_timeout,
        )
        return connector, None

    raise ValueError(f"unsupported proxy scheme: {scheme!r}")


def _normalize_proxy_url_for_connector(proxy_url: str) -> tuple[str, str]:
    """
    标准化连接器使用的代理地址，并兼容 socket5/socket5h 别名。

    Args:
        proxy_url (str): 原始代理地址。

    Returns:
        tuple[str, str]: 标准化后的代理地址和规范化协议名。
    """

    parsed = urlsplit(proxy_url)
    scheme = parsed.scheme.lower()
    alias_map = {
        "socket5": "socks5",
        "socket5h": "socks5h",
    }
    normalized_scheme = alias_map.get(scheme, scheme)
    if normalized_scheme == "socks5h":
        # aiohttp-socks / python-socks 只接受 socks5://，是否远程解析由 rdns 参数控制。
        normalized_url = urlunsplit(parsed._replace(scheme="socks5"))
        return normalized_url, normalized_scheme
    if normalized_scheme != scheme:
        return urlunsplit(parsed._replace(scheme=normalized_scheme)), normalized_scheme
    return proxy_url, normalized_scheme
