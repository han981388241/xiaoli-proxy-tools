"""
请求传输层抽象接口。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..request import RequestSpec
from ..response import Response
from ..session import CookieRecord, SessionState


class Transport(ABC):
    """
    请求传输层抽象接口。
    """

    @abstractmethod
    async def request(self, spec: RequestSpec, state: SessionState) -> Response:
        """
        执行单个请求。

        Args:
            spec (RequestSpec): 请求规格。
            state (SessionState): 会话状态。

        Returns:
            Response: 响应对象。
        """

    @abstractmethod
    async def close(self) -> None:
        """
        关闭传输层资源。

        Returns:
            None: 无返回值。
        """

    @abstractmethod
    def export_cookies(self) -> list[CookieRecord]:
        """
        导出传输层 Cookie。

        Returns:
            list[CookieRecord]: Cookie 列表。
        """

    @abstractmethod
    def import_cookies(self, cookies: list[CookieRecord], *, merge: bool = True) -> None:
        """
        导入 Cookie 到传输层。

        Args:
            cookies (list[CookieRecord]): Cookie 列表。
            merge (bool): 是否合并已有 Cookie。

        Returns:
            None: 无返回值。
        """
