"""
代理请求规格模型。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RequestSpec:
    """
    描述一次待发送的 HTTP 请求。

    Args:
        method (str): HTTP 方法。
        url (str): 请求 URL。
        headers (dict[str, str] | None): 请求头。
        params (dict[str, Any] | None): 查询参数。
        data (Any): 表单或原始请求体。
        json (Any): JSON 请求体。
        timeout (float | None): 单请求总超时时间。
        tag (str | None): 请求标签。
        meta (dict[str, Any]): 自定义上下文。

    Returns:
        None: 数据对象无返回值。
    """

    method: str
    url: str
    headers: dict[str, str] | None = None
    params: dict[str, Any] | None = None
    data: Any = None
    json: Any = None
    timeout: float | None = None
    tag: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """
        将请求规格转换为可序列化字典。

        Returns:
            dict[str, Any]: 请求规格字典。
        """

        return {
            "method": self.method,
            "url": self.url,
            "headers": self.headers,
            "params": self.params,
            "data": self.data,
            "json": self.json,
            "timeout": self.timeout,
            "tag": self.tag,
            "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RequestSpec":
        """
        从字典恢复请求规格。

        Args:
            data (dict[str, Any]): 请求规格字典。

        Returns:
            RequestSpec: 请求规格对象。
        """

        return cls(
            method=str(data["method"]),
            url=str(data["url"]),
            headers=data.get("headers"),
            params=data.get("params"),
            data=data.get("data"),
            json=data.get("json"),
            timeout=data.get("timeout"),
            tag=data.get("tag"),
            meta=dict(data.get("meta") or {}),
        )
