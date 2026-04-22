"""
代理生成器使用的核心模型。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ProxyNode:
    """
    描述一条可直接使用的代理节点信息。

    Args:
        session_id (str): 代理会话标识。
        proxy_url (str): 主代理地址。
        proxies (dict[str, str]): 多协议代理映射。
        country_code (str): 国家代码。
        duration_minutes (int): 代理会话时长，单位分钟。

    Returns:
        None: 无返回值。

    Raises:
        无。
    """

    session_id: str
    proxy_url: str
    proxies: dict[str, str]
    country_code: str = "000"
    duration_minutes: int = 5

    @property
    def key(self) -> str:
        """
        返回代理节点唯一键。

        Args:
            无。

        Returns:
            str: 代理会话键。

        Raises:
            无。
        """

        return self.session_id
