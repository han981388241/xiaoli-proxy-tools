"""
单进程多代理客户端集群。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
from collections import deque
from dataclasses import dataclass
from typing import Any, AsyncIterator, Iterable, Iterator

from .client import ProxyClient
from .errors import ProxyClientError
from .metrics import ClientMetrics
from .request import RequestSpec
from .response import Headers, Response

_LOGGER = logging.getLogger("proxy_scheduler_client.cluster")


class FailurePolicy:
    """
    客户端失败处理策略常量。
    """

    RETRY_ON_NEXT = "retry_on_next"
    SKIP = "skip"
    FAIL_ALL = "fail_all"


@dataclass(slots=True)
class RoutingStrategy:
    """
    客户端路由策略。

    Args:
        mode (str): 路由模式，支持 round_robin、random、by_tag。

    Returns:
        None: 数据对象无返回值。
    """

    mode: str = "round_robin"

    def select_index(self, clients: list[ProxyClient], spec: RequestSpec, cursor: int) -> int:
        """
        选择客户端下标。

        Args:
            clients (list[ProxyClient]): 客户端列表。
            spec (RequestSpec): 请求规格。
            cursor (int): 当前轮询游标。

        Returns:
            int: 客户端下标。

        Raises:
            ValueError: 路由模式不支持时抛出。
        """

        if not clients:
            raise ValueError("clients cannot be empty")
        if self.mode == "round_robin":
            return cursor % len(clients)
        if self.mode == "random":
            return random.randrange(0, len(clients))
        if self.mode == "by_tag":
            key = spec.tag or spec.url
            digest = hashlib.md5(key.encode("utf-8")).hexdigest()
            return int(digest, 16) % len(clients)
        raise ValueError(f"unsupported routing mode: {self.mode!r}")


class ClientCluster:
    """
    单进程多 ProxyClient 调度器。
    """

    def __init__(
        self,
        clients: Iterable[ProxyClient],
        *,
        routing: RoutingStrategy | None = None,
        failure_policy: str = FailurePolicy.RETRY_ON_NEXT,
        verbose: bool = False,
    ) -> None:
        """
        初始化客户端集群。

        Args:
            clients (Iterable[ProxyClient]): 客户端实例列表。
            routing (RoutingStrategy | None): 路由策略。
            failure_policy (str): 失败处理策略。
            verbose (bool): 是否打印中文调试日志。

        Returns:
            None: 无返回值。

        Raises:
            ValueError: 客户端列表为空时抛出。
        """

        self.clients = list(clients)
        if not self.clients:
            raise ValueError("clients cannot be empty")
        self.routing = routing or RoutingStrategy()
        self.failure_policy = failure_policy
        self.verbose = verbose
        self._cursor = 0
        self._closed = False

    async def __aenter__(self) -> "ClientCluster":
        """
        进入异步上下文。

        Returns:
            ClientCluster: 当前集群实例。
        """

        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        """
        退出异步上下文并关闭所有客户端。

        Args:
            exc_type (Any): 异常类型。
            exc (Any): 异常对象。
            traceback (Any): 异常堆栈。

        Returns:
            None: 无返回值。
        """

        await self.close_all()

    async def request(
        self,
        spec: RequestSpec | dict[str, Any],
        *,
        return_exceptions: bool = True,
    ) -> Response:
        """
        按路由策略执行单个请求。

        Args:
            spec (RequestSpec | dict[str, Any]): 请求规格。
            return_exceptions (bool): 是否把异常包装进 Response。

        Returns:
            Response: 响应对象。

        Raises:
            ProxyClientError: 所有客户端失败且 return_exceptions 为 False 时抛出。
        """

        request_spec = spec if isinstance(spec, RequestSpec) else RequestSpec.from_dict(spec)
        ordered_clients = self._ordered_clients(request_spec)
        last_error: ProxyClientError | None = None
        last_response: Response | None = None

        for client in ordered_clients:
            response = await client.request(request_spec, return_exceptions=True)
            if response.error is None:
                return response
            last_response = response
            if isinstance(response.error, ProxyClientError):
                last_error = response.error
            self._log(
                f"[客户端集群] 请求失败 - URL: {request_spec.url} 状态: None "
                f"重试: 1/1 代理: {client.current_proxy_masked()} 策略: {self.failure_policy}"
            )
            if self.failure_policy == FailurePolicy.FAIL_ALL:
                break

        if return_exceptions and last_response is not None:
            return last_response
        if last_error is not None:
            raise last_error
        raise ProxyClientError("客户端集群请求失败")

    async def stream(
        self,
        specs: Iterable[RequestSpec | dict[str, Any]],
        *,
        return_exceptions: bool = True,
    ) -> AsyncIterator[Response]:
        """
        以背压方式流式执行集群请求。

        Args:
            specs (Iterable[RequestSpec | dict[str, Any]]): 请求规格迭代器。
            return_exceptions (bool): 是否把异常包装进 Response。

        Yields:
            Response: 响应对象。
        """

        iterator = iter(specs)
        pending: dict[asyncio.Future[Response], tuple[RequestSpec, ProxyClient | None]] = {}
        pending_by_client: dict[int, int] = {id(client): 0 for client in self.clients}
        backlog_by_client: dict[int, deque[RequestSpec]] = {id(client): deque() for client in self.clients}
        exhausted = False

        try:
            exhausted = self._fill_stream_window(
                iterator,
                pending,
                pending_by_client,
                backlog_by_client,
                exhausted,
                return_exceptions,
            )
            while pending:
                done, _ = await asyncio.wait(
                    pending,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                first_error: BaseException | None = None
                for task in done:
                    spec, client = pending.pop(task)
                    if client is not None:
                        pending_by_client[id(client)] = max(0, pending_by_client[id(client)] - 1)
                    try:
                        yield task.result()
                    except Exception as exc:
                        proxy_snapshot = client.current_proxy_masked() if client is not None else "cluster"
                        if self.verbose:
                            self._log(
                                f"[客户端集群] 流式任务异常 - URL: {spec.url} 状态: None "
                                f"重试: 1/1 代理: {proxy_snapshot} "
                                f"错误: {type(exc).__name__}: {exc}"
                            )
                        if not return_exceptions:
                            if first_error is None:
                                first_error = exc
                            continue
                        yield _cluster_error_response(
                            spec,
                            ProxyClientError(
                                str(exc),
                                proxy_snapshot=proxy_snapshot,
                                request_tag=spec.tag,
                                detail={"type": type(exc).__name__},
                            ),
                        )
                if first_error is not None:
                    raise first_error
                exhausted = self._fill_stream_window(
                    iterator,
                    pending,
                    pending_by_client,
                    backlog_by_client,
                    exhausted,
                    return_exceptions,
                )
        finally:
            cancelled = list(pending)
            for task in cancelled:
                task.cancel()
            if cancelled:
                cleanup = asyncio.create_task(_await_cancelled_tasks(cancelled))
                cleanup.add_done_callback(_silence_task_result)

    async def gather(
        self,
        specs: Iterable[RequestSpec | dict[str, Any]],
        *,
        return_exceptions: bool = True,
    ) -> list[Response]:
        """
        执行集群多请求并返回响应列表。

        Args:
            specs (Iterable[RequestSpec | dict[str, Any]]): 请求规格迭代器。
            return_exceptions (bool): 是否把异常包装进 Response。

        Returns:
            list[Response]: 响应列表。
        """

        responses: list[Response] = []
        async for response in self.stream(specs, return_exceptions=return_exceptions):
            responses.append(response)
        return responses

    def metrics_snapshot(self) -> dict[str, Any]:
        """
        返回聚合指标快照。

        Returns:
            dict[str, Any]: 指标快照。
        """

        metrics = ClientMetrics()
        for client in self.clients:
            metrics.merge(client.metrics)
        return metrics.snapshot()

    async def close_all(self) -> None:
        """
        关闭所有客户端。

        Returns:
            None: 无返回值。
        """

        if self._closed:
            return
        await asyncio.gather(*(client.close() for client in self.clients), return_exceptions=True)
        self._closed = True
        self._log("[客户端集群] 关闭集群 - URL: - 状态: 完成 重试: 0/0 代理: 多代理")

    def _fill_stream_one(
        self,
        iterator: Iterator[RequestSpec | dict[str, Any]],
        pending: dict[asyncio.Future[Response], tuple[RequestSpec, ProxyClient | None]],
        pending_by_client: dict[int, int],
        backlog_by_client: dict[int, deque[RequestSpec]],
        input_exhausted: bool,
        return_exceptions: bool,
    ) -> tuple[bool, bool]:
        """
        为集群流式请求增量补充一个 in-flight 任务。

        Args:
            iterator (Iterator[RequestSpec | dict[str, Any]]): 请求规格迭代器。
            pending (dict[asyncio.Future[Response], tuple[RequestSpec, ProxyClient]]): 运行中的任务映射。
            pending_by_client (dict[int, int]): 每个客户端的运行中任务数量。
            backlog_by_client (dict[int, deque[RequestSpec]]): 按客户端分片的积压请求。
            input_exhausted (bool): 输入迭代器是否已经耗尽。
            return_exceptions (bool): 是否把异常包装进 Response。

        Returns:
            tuple[bool, bool]: 是否耗尽输入、是否成功补充任务。
        """

        for client in self.clients:
            client_key = id(client)
            if not backlog_by_client[client_key]:
                continue
            if pending_by_client.get(client_key, 0) >= client.limits.concurrency:
                continue
            request_spec = backlog_by_client[client_key].popleft()
            self._schedule_stream_task(
                request_spec,
                client,
                pending,
                pending_by_client,
                return_exceptions,
                advance_cursor_to=None,
            )
            return input_exhausted, True

        if input_exhausted:
            return True, False

        try:
            spec = next(iterator)
        except StopIteration:
            return True, False
        except Exception as exc:
            request_spec = RequestSpec(method="GET", url="", tag="input-error")
            self._schedule_completed_stream_response(
                request_spec,
                _cluster_error_response(
                    request_spec,
                    ProxyClientError(
                        str(exc),
                        proxy_snapshot="cluster",
                        request_tag=request_spec.tag,
                        detail={"type": type(exc).__name__},
                    ),
                ),
                pending,
            )
            return True, True
        try:
            request_spec = spec if isinstance(spec, RequestSpec) else RequestSpec.from_dict(spec)
        except Exception as exc:
            request_spec = RequestSpec(method="GET", url="", tag="input-error")
            self._schedule_completed_stream_response(
                request_spec,
                _cluster_error_response(
                    request_spec,
                    ProxyClientError(
                        str(exc),
                        proxy_snapshot="cluster",
                        request_tag=request_spec.tag,
                        detail={"type": type(exc).__name__},
                    ),
                ),
                pending,
            )
            return False, True

        client, client_index, ready = self._select_stream_client(request_spec, pending_by_client)
        if not ready:
            backlog_by_client[id(client)].append(request_spec)
            return False, False

        self._schedule_stream_task(
            request_spec,
            client,
            pending,
            pending_by_client,
            return_exceptions,
            advance_cursor_to=client_index if self.routing.mode == "round_robin" else None,
        )
        return False, True

    def _fill_stream_window(
        self,
        iterator: Iterator[RequestSpec | dict[str, Any]],
        pending: dict[asyncio.Future[Response], tuple[RequestSpec, ProxyClient | None]],
        pending_by_client: dict[int, int],
        backlog_by_client: dict[int, deque[RequestSpec]],
        input_exhausted: bool,
        return_exceptions: bool,
    ) -> bool:
        """
        尽量填满集群流式请求窗口。

        Args:
            iterator (Iterator[RequestSpec | dict[str, Any]]): 请求规格迭代器。
            pending (dict[asyncio.Future[Response], tuple[RequestSpec, ProxyClient]]): 运行中的任务映射。
            pending_by_client (dict[int, int]): 每个客户端的运行中任务数量。
            backlog_by_client (dict[int, deque[RequestSpec]]): 按客户端分片的积压请求。
            input_exhausted (bool): 输入迭代器是否已经耗尽。
            return_exceptions (bool): 是否把异常包装进 Response。

        Returns:
            bool: 输入迭代器是否已经耗尽。
        """

        limit = self._stream_window_limit()
        while len(pending) < limit:
            input_exhausted, progressed = self._fill_stream_one(
                iterator,
                pending,
                pending_by_client,
                backlog_by_client,
                input_exhausted,
                return_exceptions,
            )
            if progressed:
                continue
            if self._all_stream_clients_full(pending_by_client):
                break
            if input_exhausted and not self._has_dispatchable_backlog(backlog_by_client, pending_by_client):
                break
        return input_exhausted

    def _schedule_stream_task(
        self,
        request_spec: RequestSpec,
        client: ProxyClient,
        pending: dict[asyncio.Future[Response], tuple[RequestSpec, ProxyClient | None]],
        pending_by_client: dict[int, int],
        return_exceptions: bool,
        *,
        advance_cursor_to: int | None = None,
    ) -> None:
        """
        创建集群流式请求任务。

        Args:
            request_spec (RequestSpec): 请求规格。
            client (ProxyClient): 目标客户端。
            pending (dict[asyncio.Future[Response], tuple[RequestSpec, ProxyClient]]): 运行中的任务映射。
            pending_by_client (dict[int, int]): 每个客户端的运行中任务数量。
            return_exceptions (bool): 是否把异常包装进 Response。
            advance_cursor_to (int | None): 若不为 None，则把轮询游标推进到指定下标的下一位。

        Returns:
            None: 无返回值。
        """

        task = asyncio.create_task(client.request(request_spec, return_exceptions=return_exceptions))
        pending[task] = (request_spec, client)
        pending_by_client[id(client)] = pending_by_client.get(id(client), 0) + 1
        if advance_cursor_to is not None:
            self._cursor = advance_cursor_to + 1

    def _schedule_completed_stream_response(
        self,
        request_spec: RequestSpec,
        response: Response,
        pending: dict[asyncio.Future[Response], tuple[RequestSpec, ProxyClient | None]],
    ) -> None:
        """
        写入已经完成的集群错误响应。

        Args:
            request_spec (RequestSpec): 请求规格。
            response (Response): 响应对象。
            pending (dict[asyncio.Future[Response], tuple[RequestSpec, ProxyClient | None]]): 运行中的任务映射。

        Returns:
            None: 无返回值。
        """

        task = _completed_response_task(response)
        pending[task] = (request_spec, None)

    def _select_stream_client(
        self,
        spec: RequestSpec,
        pending_by_client: dict[int, int],
    ) -> tuple[ProxyClient, int, bool]:
        """
        为流式请求选择一个客户端。

        Args:
            spec (RequestSpec): 请求规格。
            pending_by_client (dict[int, int]): 每个客户端的运行中任务数量。

        Returns:
            tuple[ProxyClient, int, bool]: 客户端、下标、是否有可用容量。
        """

        if self.routing.mode == "round_robin":
            start = self._cursor % len(self.clients)
            for offset in range(len(self.clients)):
                index = (start + offset) % len(self.clients)
                client = self.clients[index]
                if pending_by_client.get(id(client), 0) < client.limits.concurrency:
                    return client, index, True
            client = self.clients[start]
            return client, start, False

        if self.routing.mode == "random":
            ready_indexes = [
                index
                for index, client in enumerate(self.clients)
                if pending_by_client.get(id(client), 0) < client.limits.concurrency
            ]
            if ready_indexes:
                index = random.choice(ready_indexes)
                return self.clients[index], index, True
            index = random.randrange(0, len(self.clients))
            return self.clients[index], index, False

        index = self.routing.select_index(self.clients, spec, self._cursor)
        client = self.clients[index]
        return client, index, pending_by_client.get(id(client), 0) < client.limits.concurrency

    def _has_dispatchable_backlog(
        self,
        backlog_by_client: dict[int, deque[RequestSpec]],
        pending_by_client: dict[int, int],
    ) -> bool:
        """
        判断是否存在可以立即投递的积压请求。

        Args:
            backlog_by_client (dict[int, deque[RequestSpec]]): 按客户端分片的积压请求。
            pending_by_client (dict[int, int]): 每个客户端的运行中任务数量。

        Returns:
            bool: 存在可立即投递的积压请求返回 True。
        """

        for client in self.clients:
            client_key = id(client)
            if backlog_by_client[client_key] and pending_by_client.get(client_key, 0) < client.limits.concurrency:
                return True
        return False

    def _all_stream_clients_full(self, pending_by_client: dict[int, int]) -> bool:
        """
        判断所有客户端是否都达到流式并发上限。

        Args:
            pending_by_client (dict[int, int]): 每个客户端的运行中任务数量。

        Returns:
            bool: 全部满载返回 True。
        """

        return all(pending_by_client.get(id(client), 0) >= client.limits.concurrency for client in self.clients)

    def _stream_window_limit(self) -> int:
        """
        返回集群全局 in-flight 窗口大小。

        Returns:
            int: 全局窗口大小。
        """

        return max(1, sum(client.limits.concurrency for client in self.clients))

    def _ordered_clients(self, spec: RequestSpec) -> list[ProxyClient]:
        """
        返回请求可尝试的客户端顺序。

        Args:
            spec (RequestSpec): 请求规格。

        Returns:
            list[ProxyClient]: 客户端顺序列表。
        """

        index = self.routing.select_index(self.clients, spec, self._cursor)
        if self.routing.mode == "round_robin":
            self._cursor += 1
        if self.failure_policy in {FailurePolicy.FAIL_ALL, FailurePolicy.SKIP}:
            return [self.clients[index]]
        return self.clients[index:] + self.clients[:index]

    def _log(self, message: str) -> None:
        """
        输出中文调试日志。

        Args:
            message (str): 日志内容。

        Returns:
            None: 无返回值。
        """

        if not self.verbose:
            return
        if not logging.getLogger().handlers and not _LOGGER.handlers:
            logging.basicConfig(level=logging.INFO, format="%(message)s")
        _LOGGER.info(message)


def _cluster_error_response(spec: RequestSpec, error: ProxyClientError) -> Response:
    """
    构造集群输入阶段的失败响应。
    Args:
        spec (RequestSpec): 请求规格。
        error (ProxyClientError): 输入阶段异常。
    Returns:
        Response: 失败响应对象。
    """

    return Response(
        status=None,
        headers=Headers(),
        url=spec.url,
        final_url=spec.url,
        method=spec.method.upper(),
        elapsed_ms=0.0,
        request_tag=spec.tag,
        content=b"",
        content_path=None,
        encoding=None,
        proxy_snapshot="cluster",
        error=error,
        history=[],
    )


def _completed_response_task(response: Response) -> asyncio.Future[Response]:
    """
    创建已经完成的响应任务。
    Args:
        response (Response): 响应对象。
    Returns:
        asyncio.Future[Response]: 已完成任务。
    """

    future: asyncio.Future[Response] = asyncio.get_running_loop().create_future()
    future.set_result(response)
    return future


async def _await_cancelled_tasks(tasks: list[asyncio.Future[Response]]) -> None:
    """
    在后台等待已取消任务收尾，避免事件循环关闭时输出未回收任务告警。

    Args:
        tasks (list[asyncio.Future[Response]]): 已取消的任务列表。

    Returns:
        None: 无返回值。
    """

    await asyncio.gather(*tasks, return_exceptions=True)


def _silence_task_result(task: asyncio.Future[Any]) -> None:
    """
    吞掉后台清理任务的异常结果，避免未消费异常告警。

    Args:
        task (asyncio.Future[Any]): 后台任务。

    Returns:
        None: 无返回值。
    """

    try:
        task.result()
    except Exception:
        return


__all__ = ["ClientCluster", "FailurePolicy", "RoutingStrategy"]
