"""
代理请求客户端异常体系。
"""

from __future__ import annotations

from typing import Any


class ProxyClientError(Exception):
    """
    代理请求客户端异常基类。
    """

    def __init__(
        self,
        message: str,
        *,
        proxy_snapshot: str = "",
        request_tag: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        """
        初始化客户端异常。

        Args:
            message (str): 错误消息。
            proxy_snapshot (str): 脱敏代理快照。
            request_tag (str | None): 请求标签。
            detail (dict[str, Any] | None): 附加上下文。

        Returns:
            None: 无返回值。
        """

        super().__init__(message)
        self.message = message
        self.proxy_snapshot = proxy_snapshot
        self.request_tag = request_tag
        self.detail = detail or {}

    def to_dict(self) -> dict[str, Any]:
        """
        将异常转换为可序列化字典。

        Returns:
            dict[str, Any]: 异常字典。
        """

        return {
            "type": type(self).__name__,
            "message": self.message,
            "proxy_snapshot": self.proxy_snapshot,
            "request_tag": self.request_tag,
            "detail": self.detail,
        }


class TransportError(ProxyClientError):
    """
    传输层异常。
    """


class ProxyConnectionError(TransportError):
    """
    代理网关连接异常。
    """


class ProxyAuthError(TransportError):
    """
    代理认证异常。
    """


class TargetConnectionError(TransportError):
    """
    目标站连接异常。
    """


class TLSError(TransportError):
    """
    TLS 握手异常。
    """


class ProxyTimeoutError(ProxyClientError):
    """
    请求超时异常基类。
    """


class ConnectTimeoutError(ProxyTimeoutError):
    """
    连接超时异常。
    """


class ReadTimeoutError(ProxyTimeoutError):
    """
    读取超时异常。
    """


class TotalTimeoutError(ProxyTimeoutError):
    """
    总超时异常。
    """


class ProtocolError(ProxyClientError):
    """
    HTTP 协议异常。
    """


class SessionStateError(ProxyClientError):
    """
    会话状态导入导出异常。
    """


class ClientClosedError(ProxyClientError):
    """
    客户端已关闭异常。
    """


class TransportDependencyMissing(ImportError):
    """
    传输层缺少可选依赖时抛出的异常。
    """

    def __init__(self, protocol: str, package: str, install_command: str) -> None:
        """
        初始化依赖缺失异常。

        Args:
            protocol (str): 目标协议。
            package (str): 缺少的包名。
            install_command (str): 安装命令。

        Returns:
            None: 无返回值。
        """

        self.protocol = protocol
        self.package = package
        self.install_command = install_command
        super().__init__(
            f"协议 {protocol!r} 需要安装 {package!r}，请执行：{install_command}"
        )
