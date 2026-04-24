"""
代理请求客户端会话状态快照。
"""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from typing import Any

from .errors import SessionStateError


@dataclass(slots=True)
class CookieRecord:
    """
    可序列化 Cookie 记录。

    Args:
        name (str): Cookie 名称。
        value (str): Cookie 值。
        domain (str): Cookie 域名。
        path (str): Cookie 路径。
        expires (float | None): 过期时间戳。
        secure (bool): 是否仅 HTTPS。
        httponly (bool): 是否 HTTP Only。
        samesite (str | None): SameSite 属性。

    Returns:
        None: 数据对象无返回值。
    """

    name: str
    value: str
    domain: str = ""
    path: str = "/"
    expires: float | None = None
    secure: bool = False
    httponly: bool = False
    samesite: str | None = None

    def __post_init__(self) -> None:
        """
        规范化 Cookie 属性。

        Returns:
            None: 无返回值。

        Raises:
            ValueError: SameSite 不合法时抛出。
        """

        if self.samesite is None:
            return
        value = str(self.samesite).strip().lower()
        mapping = {"lax": "Lax", "strict": "Strict", "none": "None"}
        if value not in mapping:
            raise ValueError("samesite must be Lax, Strict or None")
        self.samesite = mapping[value]

    def to_dict(self) -> dict[str, Any]:
        """
        转换为字典。

        Returns:
            dict[str, Any]: Cookie 字典。
        """

        return {
            "name": self.name,
            "value": self.value,
            "domain": self.domain,
            "path": self.path,
            "expires": self.expires,
            "secure": self.secure,
            "httponly": self.httponly,
            "samesite": self.samesite,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CookieRecord":
        """
        从字典恢复 Cookie。

        Args:
            data (dict[str, Any]): Cookie 字典。

        Returns:
            CookieRecord: Cookie 记录。
        """

        return cls(
            name=str(data["name"]),
            value=str(data.get("value", "")),
            domain=str(data.get("domain", "")),
            path=str(data.get("path", "/")),
            expires=data.get("expires"),
            secure=bool(data.get("secure", False)),
            httponly=bool(data.get("httponly", False)),
            samesite=data.get("samesite"),
        )


@dataclass(slots=True)
class SessionState:
    """
    完整会话状态快照。

    Args:
        schema_version (int): 快照格式版本。
        cookies (list[CookieRecord]): Cookie 列表。
        headers_sticky (dict[str, str]): 会话级请求头。
        default_headers (dict[str, str]): 默认请求头。
        user_agent (str): User-Agent。
        proxy_hint (str | None): 脱敏代理提示。
        local_storage (dict[str, Any]): 用户自定义本地状态。
        created_at (float): 创建时间戳。
        source_proxy_fingerprint (str | None): 来源代理指纹。

    Returns:
        None: 数据对象无返回值。
    """

    schema_version: int = 1
    cookies: list[CookieRecord] = field(default_factory=list)
    headers_sticky: dict[str, str] = field(default_factory=dict)
    default_headers: dict[str, str] = field(default_factory=dict)
    user_agent: str = ""
    proxy_hint: str | None = None
    local_storage: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    source_proxy_fingerprint: str | None = None

    def copy(self) -> "SessionState":
        """
        深拷贝会话状态。

        Returns:
            SessionState: 新的会话状态对象。
        """

        return copy.deepcopy(self)

    def to_dict(self) -> dict[str, Any]:
        """
        转换为可序列化字典。

        Returns:
            dict[str, Any]: 会话状态字典。
        """

        return {
            "schema_version": self.schema_version,
            "cookies": [cookie.to_dict() for cookie in self.cookies],
            "headers_sticky": dict(self.headers_sticky),
            "default_headers": dict(self.default_headers),
            "user_agent": self.user_agent,
            "proxy_hint": self.proxy_hint,
            "local_storage": copy.deepcopy(self.local_storage),
            "created_at": self.created_at,
            "source_proxy_fingerprint": self.source_proxy_fingerprint,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionState":
        """
        从字典恢复会话状态。

        Args:
            data (dict[str, Any]): 会话状态字典。

        Returns:
            SessionState: 会话状态对象。

        Raises:
            SessionStateError: 快照版本不支持时抛出。
        """

        version = int(data.get("schema_version", 1))
        if version < 1:
            raise SessionStateError(f"不支持的 SessionState 版本: {version}")
        if version > 1:
            raise SessionStateError(f"不支持的 SessionState 版本: {version}")
        return cls(
            schema_version=version,
            cookies=[CookieRecord.from_dict(item) for item in data.get("cookies", [])],
            headers_sticky={str(k): str(v) for k, v in dict(data.get("headers_sticky") or {}).items()},
            default_headers={str(k): str(v) for k, v in dict(data.get("default_headers") or {}).items()},
            user_agent=str(data.get("user_agent", "")),
            proxy_hint=data.get("proxy_hint"),
            local_storage=copy.deepcopy(data.get("local_storage") or {}),
            created_at=float(data.get("created_at", time.time())),
            source_proxy_fingerprint=data.get("source_proxy_fingerprint"),
        )
