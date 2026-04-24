"""
代理请求响应模型。
"""

from __future__ import annotations

import json as json_module
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .errors import ProxyClientError


@dataclass(slots=True)
class Headers:
    """
    轻量响应头容器。

    Args:
        items (list[tuple[str, str]]): 响应头键值列表。

    Returns:
        None: 数据对象无返回值。
    """

    items: list[tuple[str, str]] = field(default_factory=list)

    def get(self, name: str, default: str | None = None) -> str | None:
        """
        按名称获取响应头。

        Args:
            name (str): 响应头名称。
            default (str | None): 默认值。

        Returns:
            str | None: 响应头值。
        """

        target = name.lower()
        for key, value in reversed(self.items):
            if key.lower() == target:
                return value
        return default

    def to_dict(self) -> dict[str, str]:
        """
        转换为普通字典。

        Returns:
            dict[str, str]: 响应头字典。
        """

        return {key: value for key, value in self.items}

    @classmethod
    def from_mapping(cls, headers: Any) -> "Headers":
        """
        从映射对象创建响应头容器。

        Args:
            headers (Any): 响应头映射。

        Returns:
            Headers: 响应头容器。
        """

        if hasattr(headers, "items"):
            return cls(items=[(str(key), str(value)) for key, value in headers.items()])
        return cls(items=[(str(key), str(value)) for key, value in headers])


@dataclass(slots=True)
class RedirectRecord:
    """
    重定向记录。

    Args:
        status (int): 重定向响应状态码。
        url (str): 重定向 URL。

    Returns:
        None: 数据对象无返回值。
    """

    status: int
    url: str

    def to_dict(self) -> dict[str, Any]:
        """
        转换为字典。

        Returns:
            dict[str, Any]: 重定向记录字典。
        """

        return {"status": self.status, "url": self.url}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RedirectRecord":
        """
        从字典恢复重定向记录。

        Args:
            data (dict[str, Any]): 重定向记录字典。

        Returns:
            RedirectRecord: 重定向记录。
        """

        return cls(status=int(data["status"]), url=str(data["url"]))


@dataclass(slots=True)
class Response:
    """
    与 aiohttp 完全解耦的响应对象。

    Args:
        status (int | None): HTTP 状态码。
        headers (Headers): 响应头。
        url (str): 原始请求 URL。
        final_url (str): 最终响应 URL。
        method (str): HTTP 方法。
        elapsed_ms (float): 请求耗时，单位毫秒。
        request_tag (str | None): 请求标签。
        content (bytes): 响应体内容。
        content_path (str | None): 大响应体落盘路径。
        encoding (str | None): 响应编码。
        proxy_snapshot (str): 脱敏代理标识。
        error (ProxyClientError | None): 请求失败异常。
        history (list[RedirectRecord]): 重定向链路。

    Returns:
        None: 数据对象无返回值。
    """

    status: int | None
    headers: Headers
    url: str
    final_url: str
    method: str
    elapsed_ms: float
    request_tag: str | None = None
    content: bytes = b""
    content_path: str | None = None
    encoding: str | None = None
    proxy_snapshot: str = ""
    error: ProxyClientError | None = None
    history: list[RedirectRecord] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """
        判断响应是否成功。

        Returns:
            bool: 成功返回 True，失败返回 False。
        """

        return self.error is None and self.status is not None and 200 <= self.status < 400

    def body(self) -> bytes:
        """
        返回响应体字节。

        Returns:
            bytes: 响应体字节。
        """

        if self.content_path:
            return Path(self.content_path).read_bytes()
        return self.content

    def text(self) -> str:
        """
        返回响应文本。

        Returns:
            str: 响应文本。
        """

        encoding = self.encoding or "utf-8"
        return self.body().decode(encoding, errors="replace")

    def json(self) -> Any:
        """
        解析响应 JSON。

        Returns:
            Any: JSON 解析结果。
        """

        return json_module.loads(self.text())

    def iter_lines(self) -> Iterator[bytes]:
        """
        逐行迭代响应体。

        Yields:
            bytes: 响应体行内容。
        """

        if self.content_path:
            with open(self.content_path, "rb") as file:
                for line in file:
                    yield line.rstrip(b"\r\n")
            return

        for line in self.content.splitlines():
            yield line

    def close(self) -> None:
        """
        清理响应关联的临时落盘文件。

        Returns:
            None: 无返回值。
        """

        if not self.content_path:
            return
        path = Path(self.content_path)
        try:
            path.unlink(missing_ok=True)
        finally:
            self.content_path = None

    def __enter__(self) -> "Response":
        """
        进入响应上下文。

        Returns:
            Response: 当前响应对象。
        """

        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        """
        退出响应上下文并清理临时文件。

        Args:
            exc_type (Any): 异常类型。
            exc (Any): 异常对象。
            traceback (Any): 异常堆栈。

        Returns:
            None: 无返回值。
        """

        self.close()

    def to_dict(self) -> dict[str, Any]:
        """
        将响应对象转换为可序列化字典。

        Returns:
            dict[str, Any]: 响应字典。
        """

        return {
            "status": self.status,
            "headers": self.headers.items,
            "url": self.url,
            "final_url": self.final_url,
            "method": self.method,
            "elapsed_ms": self.elapsed_ms,
            "request_tag": self.request_tag,
            "content": b"" if self.content_path else self.content,
            "content_path": self.content_path,
            "encoding": self.encoding,
            "proxy_snapshot": self.proxy_snapshot,
            "error": self.error.to_dict() if self.error else None,
            "history": [item.to_dict() for item in self.history],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Response":
        """
        从字典恢复响应对象。

        Args:
            data (dict[str, Any]): 响应字典。

        Returns:
            Response: 响应对象。
        """

        error = None
        if data.get("error"):
            error_data = data["error"]
            error = ProxyClientError(
                str(error_data.get("message", "")),
                proxy_snapshot=str(error_data.get("proxy_snapshot", "")),
                request_tag=error_data.get("request_tag"),
                detail=dict(error_data.get("detail") or {}),
            )
        return cls(
            status=data.get("status"),
            headers=Headers(items=[(str(k), str(v)) for k, v in data.get("headers", [])]),
            url=str(data.get("url", "")),
            final_url=str(data.get("final_url", "")),
            method=str(data.get("method", "")),
            elapsed_ms=float(data.get("elapsed_ms", 0.0)),
            request_tag=data.get("request_tag"),
            content=_restore_content(data.get("content", b"")),
            content_path=data.get("content_path"),
            encoding=data.get("encoding"),
            proxy_snapshot=str(data.get("proxy_snapshot", "")),
            error=error,
            history=[RedirectRecord.from_dict(item) for item in data.get("history", [])],
        )

def _restore_content(value: Any) -> bytes:
    """
    从字典字段恢复响应体字节。

    Args:
        value (Any): 响应体字段。

    Returns:
        bytes: 响应体字节。
    """

    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str):
        return value.encode("latin1")
    return b""
