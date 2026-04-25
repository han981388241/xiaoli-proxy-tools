"""
代理请求客户端运行指标。
"""

from __future__ import annotations

from collections import Counter, deque
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
    successful_requests: int = 0
    successful_latency_total_ms: float = 0.0
    successful_latency_min_ms: float = 0.0
    successful_latency_max_ms: float = 0.0
    _latencies: deque[float] = field(default_factory=deque)
    _successful_latencies: deque[float] = field(default_factory=deque)
    _status_counts: Counter[str] = field(default_factory=Counter)
    _success_status_counts: Counter[str] = field(default_factory=Counter)
    _error_counts: Counter[str] = field(default_factory=Counter)

    def __post_init__(self) -> None:
        """
        初始化延迟窗口。

        Returns:
            None: 无返回值。
        """

        self._latencies = deque(maxlen=self.latency_window)
        self._successful_latencies = deque(maxlen=self.latency_window)
        self._status_counts = Counter()
        self._success_status_counts = Counter()
        self._error_counts = Counter()

    def start(self) -> None:
        """
        记录请求开始。

        Returns:
            None: 无返回值。
        """

        self.requests_started += 1
        self.inflight += 1

    def complete(
        self,
        *,
        elapsed_ms: float,
        bytes_received: int = 0,
        status: int | None = None,
        ok: bool = False,
    ) -> None:
        """
        记录请求成功完成。

        Args:
            elapsed_ms (float): 请求耗时。
            bytes_received (int): 接收字节数。
            status (int | None): HTTP 状态码。
            ok (bool): 是否属于业务成功响应。

        Returns:
            None: 无返回值。
        """

        self.requests_completed += 1
        self.inflight = max(0, self.inflight - 1)
        self.bytes_received += bytes_received
        self._latencies.append(elapsed_ms)
        if status is not None:
            self._status_counts[str(status)] += 1
        if ok:
            self.successful_requests += 1
            self.successful_latency_total_ms += elapsed_ms
            if self.successful_latency_min_ms == 0.0 or elapsed_ms < self.successful_latency_min_ms:
                self.successful_latency_min_ms = elapsed_ms
            if elapsed_ms > self.successful_latency_max_ms:
                self.successful_latency_max_ms = elapsed_ms
            self._successful_latencies.append(elapsed_ms)
            if status is not None:
                self._success_status_counts[str(status)] += 1

    def fail(self, *, elapsed_ms: float = 0.0, error_type: str = "UnknownError") -> None:
        """
        记录请求失败。

        Args:
            elapsed_ms (float): 请求耗时。
            error_type (str): 错误类型名称。

        Returns:
            None: 无返回值。
        """

        self.requests_failed += 1
        self.inflight = max(0, self.inflight - 1)
        self._status_counts["EXCEPTION"] += 1
        self._error_counts[str(error_type or "UnknownError")] += 1
        if elapsed_ms:
            self._latencies.append(elapsed_ms)

    def snapshot(self) -> dict[str, Any]:
        """
        返回当前指标快照。

        Returns:
            dict[str, Any]: 指标快照。
        """

        latencies = sorted(self._latencies)
        successful_latencies = sorted(self._successful_latencies)
        p50 = self._percentile(latencies, 0.50)
        p99 = self._percentile(latencies, 0.99)
        success_count = self.successful_requests
        failure_count = max(0, self.requests_started - self.successful_requests)
        success_rate = (success_count / self.requests_started * 100.0) if self.requests_started else 0.0
        non_ok_completed = max(0, self.requests_completed - self.successful_requests)
        successful_avg = (
            self.successful_latency_total_ms / self.successful_requests
            if self.successful_requests
            else 0.0
        )
        hot_bucket_label, hot_bucket_count, hot_bucket_ratio = self._hot_latency_bucket(successful_latencies)
        return {
            "请求启动数": self.requests_started,
            "请求完成数": self.requests_completed,
            "请求异常数": self.requests_failed,
            "进行中请求数": self.inflight,
            "延迟P50毫秒": p50,
            "延迟P99毫秒": p99,
            "发送字节数": self.bytes_sent,
            "接收字节数": self.bytes_received,
            "成功请求数": self.successful_requests,
            "完成但非成功请求数": non_ok_completed,
            "整体未成功请求数": failure_count,
            "成功率百分比": round(success_rate, 2),
            "429限流次数": self._status_counts.get("429", 0),
            "成功请求平均耗时毫秒": round(successful_avg, 2),
            "成功请求最小耗时毫秒": round(self.successful_latency_min_ms, 2),
            "成功请求P50耗时毫秒": round(self._percentile(successful_latencies, 0.50), 2),
            "成功请求P90耗时毫秒": round(self._percentile(successful_latencies, 0.90), 2),
            "成功请求P95耗时毫秒": round(self._percentile(successful_latencies, 0.95), 2),
            "成功请求P99耗时毫秒": round(self._percentile(successful_latencies, 0.99), 2),
            "成功请求最大耗时毫秒": round(self.successful_latency_max_ms, 2),
            "成功请求耗时跨度毫秒": round(
                max(0.0, self.successful_latency_max_ms - self.successful_latency_min_ms),
                2,
            ),
            "热点耗时区间": hot_bucket_label,
            "热点耗时区间命中数": hot_bucket_count,
            "热点耗时区间占比百分比": round(hot_bucket_ratio, 2),
            "成功状态分布": dict(sorted(self._success_status_counts.items())),
            "状态分布": dict(sorted(self._status_counts.items())),
            "错误分布": dict(sorted(self._error_counts.items())),
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
        self.successful_requests += other.successful_requests
        self.successful_latency_total_ms += other.successful_latency_total_ms
        if self.successful_latency_min_ms == 0.0:
            self.successful_latency_min_ms = other.successful_latency_min_ms
        elif other.successful_latency_min_ms > 0.0:
            self.successful_latency_min_ms = min(self.successful_latency_min_ms, other.successful_latency_min_ms)
        self.successful_latency_max_ms = max(self.successful_latency_max_ms, other.successful_latency_max_ms)
        self._status_counts.update(other._status_counts)
        self._success_status_counts.update(other._success_status_counts)
        self._error_counts.update(other._error_counts)
        for latency in other._latencies:
            self._latencies.append(latency)
        for latency in other._successful_latencies:
            self._successful_latencies.append(latency)

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

    @staticmethod
    def _hot_latency_bucket(values: list[float]) -> tuple[str, int, float]:
        """
        统计成功请求最集中的延迟区间。

        Args:
            values (list[float]): 成功请求延迟样本。

        Returns:
            tuple[str, int, float]: 热点区间标签、命中数量和占比。
        """

        if not values:
            return "-", 0, 0.0
        bucket_size_ms = 500 if values[-1] <= 10000 else 1000
        buckets: Counter[str] = Counter()
        for elapsed_ms in values:
            bucket_start = int(elapsed_ms // bucket_size_ms) * bucket_size_ms
            bucket_end = bucket_start + bucket_size_ms - 1
            buckets[f"{bucket_start}-{bucket_end}ms"] += 1
        bucket_label, bucket_count = buckets.most_common(1)[0]
        return bucket_label, bucket_count, bucket_count / len(values) * 100.0
