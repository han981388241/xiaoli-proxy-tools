"""
代理请求客户端限流和超时配置。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Limits:
    """
    请求客户端运行限制。

    Args:
        concurrency (int): 协程并发数。
        connector_limit (int): 连接池总连接数。
        connector_limit_per_host (int): 单主机连接数，0 表示不限制。
        connect_timeout (float): 连接超时时间。
        read_timeout (float): 读取超时时间。
        total_timeout (float): 总超时时间。
        keepalive_timeout (float): 连接保活时间。
        dns_cache_ttl (int): DNS 缓存时间。
        queue_factor (int): 背压队列倍数。
        spool_to_disk_threshold (int): 响应体超过该字节数时落盘。
        spool_directory (str | None): 响应体落盘目录。

    Returns:
        None: 数据对象无返回值。
    """

    concurrency: int = 256
    connector_limit: int = 100
    connector_limit_per_host: int = 0
    connect_timeout: float = 10.0
    read_timeout: float = 30.0
    total_timeout: float = 60.0
    keepalive_timeout: float = 75.0
    dns_cache_ttl: int = 300
    queue_factor: int = 2
    spool_to_disk_threshold: int = 8 * 1024 * 1024
    spool_directory: str | None = None

    def __post_init__(self) -> None:
        """
        校验限制参数。

        Returns:
            None: 无返回值。

        Raises:
            ValueError: 参数不合法时抛出。
        """

        if self.concurrency <= 0:
            raise ValueError("concurrency must be > 0")
        if self.connector_limit <= 0:
            raise ValueError("connector_limit must be > 0")
        if self.queue_factor <= 0:
            raise ValueError("queue_factor must be > 0")
        if self.spool_to_disk_threshold < 0:
            raise ValueError("spool_to_disk_threshold must be >= 0")

    @property
    def queue_maxsize(self) -> int:
        """
        返回背压队列最大长度。

        Returns:
            int: 队列长度。
        """

        return self.concurrency * self.queue_factor

    def spool_path(self) -> Path | None:
        """
        返回落盘目录路径。

        Returns:
            Path | None: 落盘目录路径。
        """

        if self.spool_directory is None:
            return None
        return Path(self.spool_directory)
