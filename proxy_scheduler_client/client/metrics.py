"""
代理请求客户端运行指标。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ClientMetrics:
    """
    客户端运行指标。

    Args:
        latency_window (int): 延迟样本窗口大小。

    Returns:
        None: 数据对象无返回值。
    """

    latency_window: int = 10000
    requests_started: int = 0
    requests_completed: int = 0
    requests_failed: int = 0
    inflight: int = 0
    bytes_sent: int = 0
    bytes_received: int = 0
    _latencies: deque[float] = field(default_factory=deque)

    def __post_init__(self) -> None:
        """
        初始化延迟窗口。

        Returns:
            None: 无返回值。
        """

        self._latencies = deque(maxlen=self.latency_window)

    def start(self) -> None:
        """
        记录请求开始。

        Returns:
            None: 无返回值。
        """

        self.requests_started += 1
        self.inflight += 1

    def complete(self, *, elapsed_ms: float, bytes_received: int = 0) -> None:
        """
        记录请求成功完成。

        Args:
            elapsed_ms (float): 请求耗时。
            bytes_received (int): 接收字节数。

        Returns:
            None: 无返回值。
        """

        self.requests_completed += 1
        self.inflight = max(0, self.inflight - 1)
        self.bytes_received += bytes_received
        self._latencies.append(elapsed_ms)

    def fail(self, *, elapsed_ms: float = 0.0) -> None:
        """
        记录请求失败。

        Args:
            elapsed_ms (float): 请求耗时。

        Returns:
            None: 无返回值。
        """

        self.requests_failed += 1
        self.inflight = max(0, self.inflight - 1)
        if elapsed_ms:
            self._latencies.append(elapsed_ms)

    def snapshot(self) -> dict[str, Any]:
        """
        返回当前指标快照。

        Returns:
            dict[str, Any]: 指标快照。
        """

        latencies = sorted(self._latencies)
        p50 = self._percentile(latencies, 0.50)
        p99 = self._percentile(latencies, 0.99)
        return {
            "requests_started": self.requests_started,
            "requests_completed": self.requests_completed,
            "requests_failed": self.requests_failed,
            "inflight": self.inflight,
            "p50_latency_ms": p50,
            "p99_latency_ms": p99,
            "bytes_sent": self.bytes_sent,
            "bytes_received": self.bytes_received,
        }

    def merge(self, other: "ClientMetrics") -> None:
        """
        合并另一个指标对象。

        Args:
            other (ClientMetrics): 另一个指标对象。

        Returns:
            None: 无返回值。
        """

        self.requests_started += other.requests_started
        self.requests_completed += other.requests_completed
        self.requests_failed += other.requests_failed
        self.inflight += other.inflight
        self.bytes_sent += other.bytes_sent
        self.bytes_received += other.bytes_received
        for latency in other._latencies:
            self._latencies.append(latency)

    @staticmethod
    def _percentile(values: list[float], percent: float) -> float:
        """
        计算百分位延迟。

        Args:
            values (list[float]): 延迟样本。
            percent (float): 百分位。

        Returns:
            float: 百分位值。
        """

        if not values:
            return 0.0
        index = min(len(values) - 1, max(0, int((len(values) - 1) * percent)))
        return values[index]
