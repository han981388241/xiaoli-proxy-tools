"""
多进程代理请求运行器。
"""

from __future__ import annotations

import asyncio
import logging
import multiprocessing as mp
import queue
import time
import uuid
from typing import Any, AsyncIterator, Callable, Iterable

from .errors import ProxyClientError
from .request import RequestSpec
from .response import Headers, Response


WorkerFactory = Callable[[], Any]
MAX_WORKER_REQUEUE_ATTEMPTS = 3
_LOGGER = logging.getLogger("proxy_scheduler_client.process")


async def _process_worker_async(
    worker_index: int,
    worker_factory: WorkerFactory,
    request_queue: Any,
    response_queue: Any,
) -> None:
    """
    子进程异步消费请求队列。

    Args:
        worker_index (int): 子进程下标。
        worker_factory (WorkerFactory): 子进程内客户端构造函数。
        request_queue (Any): 请求队列。
        response_queue (Any): 响应队列。

    Returns:
        None: 无返回值。
    """

    worker = worker_factory()
    try:
        while True:
            payload = await asyncio.to_thread(request_queue.get)
            if payload is None:
                break
            batch_id, request_id, spec_data = payload
            try:
                spec = RequestSpec.from_dict(spec_data)
                response = await worker.request(spec, return_exceptions=True)
                await asyncio.to_thread(
                    response_queue.put,
                    (worker_index, batch_id, request_id, _response_to_process_dict(response), None),
                )
            except Exception as exc:
                error = {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "request_tag": spec_data.get("tag") if isinstance(spec_data, dict) else None,
                }
                await asyncio.to_thread(response_queue.put, (worker_index, batch_id, request_id, None, error))
    finally:
        await _close_worker(worker)


async def _close_worker(worker: Any) -> None:
    """
    关闭子进程内客户端或客户端集群。

    Args:
        worker (Any): 客户端或客户端集群。

    Returns:
        None: 无返回值。
    """

    try:
        if hasattr(worker, "close_all"):
            await worker.close_all()
            return
        if hasattr(worker, "close"):
            await worker.close()
    except Exception:
        return


def _process_worker_entry(worker_index: int, worker_factory: WorkerFactory, request_queue: Any, response_queue: Any) -> None:
    """
    子进程同步入口。

    Args:
        worker_index (int): 子进程下标。
        worker_factory (WorkerFactory): 子进程内客户端构造函数。
        request_queue (Any): 请求队列。
        response_queue (Any): 响应队列。

    Returns:
        None: 无返回值。
    """

    asyncio.run(_process_worker_async(worker_index, worker_factory, request_queue, response_queue))


class ProcessPoolRunner:
    """
    多进程代理请求运行器。
    """

    def __init__(
        self,
        worker_factory: WorkerFactory,
        *,
        process_count: int = 2,
        queue_size: int = 10000,
        verbose: bool = False,
    ) -> None:
        """
        初始化多进程运行器。

        Args:
            worker_factory (WorkerFactory): 子进程内客户端构造函数。
            process_count (int): 子进程数量。
            queue_size (int): 进程队列长度。
            verbose (bool): 是否打印中文调试日志。

        Returns:
            None: 无返回值。

        Raises:
            ValueError: 参数不合法时抛出。
        """

        if process_count <= 0:
            raise ValueError("process_count must be > 0")
        if queue_size <= 0:
            raise ValueError("queue_size must be > 0")
        self.worker_factory = worker_factory
        self.process_count = process_count
        self.queue_size = queue_size
        self.verbose = verbose
        self._ctx = mp.get_context("spawn")
        self._request_queues: list[Any] = []
        self._response_queue: Any | None = None
        self._processes: list[Any] = []
        self._started = False
        self._stopping = False
        self._counter = 0
        self._next_worker_index = 0
        self._stream_lock: asyncio.Lock | None = None

    async def __aenter__(self) -> "ProcessPoolRunner":
        """
        进入异步上下文并启动子进程。

        Returns:
            ProcessPoolRunner: 当前运行器。
        """

        self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        """
        退出异步上下文并停止子进程。

        Args:
            exc_type (Any): 异常类型。
            exc (Any): 异常对象。
            traceback (Any): 异常堆栈。

        Returns:
            None: 无返回值。
        """

        await self.stop()

    def start(self) -> None:
        """
        启动子进程。

        Returns:
            None: 无返回值。
        """

        if self._started:
            return
        self._request_queues = []
        self._response_queue = self._ctx.Queue(maxsize=0)
        for index in range(self.process_count):
            self._request_queues.append(self._ctx.Queue(maxsize=self.queue_size))
        self._processes = []
        self._stopping = False
        self._next_worker_index = 0
        for index in range(self.process_count):
            self._start_worker(index)
        self._started = True
        self._log(f"[进程运行器] 启动完成 - URL: - 状态: 运行中 重试: 0/0 代理: 多进程 数量: {self.process_count}")

    async def stop(self, *, timeout: float = 10.0) -> None:
        """
        停止子进程。

        Args:
            timeout (float): 等待进程退出的超时时间。

        Returns:
            None: 无返回值。
        """

        if not self._started:
            return
        self._stopping = True
        for request_queue in self._request_queues:
            try:
                request_queue.put_nowait(None)
            except (queue.Full, OSError, ValueError):
                pass
        for process in self._processes:
            await asyncio.to_thread(process.join, timeout)
            if process.is_alive():
                process.terminate()
                await asyncio.to_thread(process.join, timeout)
        for request_queue in self._request_queues:
            try:
                request_queue.close()
                request_queue.cancel_join_thread()
            except (OSError, ValueError, AttributeError):
                pass
        if self._response_queue is not None:
            try:
                self._response_queue.close()
                self._response_queue.cancel_join_thread()
            except (OSError, ValueError, AttributeError):
                pass
        self._request_queues = []
        self._processes.clear()
        self._started = False
        self._stopping = False
        self._log("[进程运行器] 停止完成 - URL: - 状态: 完成 重试: 0/0 代理: 多进程")

    async def request(self, spec: RequestSpec | dict[str, Any]) -> Response:
        """
        执行单个跨进程请求。

        Args:
            spec (RequestSpec | dict[str, Any]): 请求规格。

        Returns:
            Response: 响应对象。
        """

        responses = await self.gather([spec])
        return responses[0]

    async def stream(
        self,
        specs: Iterable[RequestSpec | dict[str, Any]],
    ) -> AsyncIterator[Response]:
        """
        以流式方式执行跨进程请求。

        Args:
            specs (Iterable[RequestSpec | dict[str, Any]]): 请求规格迭代器。

        Yields:
            Response: 响应对象。
        """

        async for _, _, response in self._stream_results(specs):
            yield response

    async def gather(self, specs: Iterable[RequestSpec | dict[str, Any]]) -> list[Response]:
        """
        执行跨进程多请求并按投递顺序返回。

        Args:
            specs (Iterable[RequestSpec | dict[str, Any]]): 请求规格迭代器。

        Returns:
            list[Response]: 响应列表。
        """

        indexed: dict[int, Response] = {}
        async for order_index, _, response in self._stream_results(specs):
            indexed[order_index] = response
        return [indexed[order_index] for order_index in sorted(indexed)]

    async def _stream_results(
        self,
        specs: Iterable[RequestSpec | dict[str, Any]],
    ) -> AsyncIterator[tuple[int, int, Response]]:
        """
        以批次隔离方式流式返回跨进程结果。

        Args:
            specs (Iterable[RequestSpec | dict[str, Any]]): 请求规格迭代器。

        Yields:
            tuple[int, int, Response]: 投递顺序、请求序号和响应对象。
        """

        async with self._get_stream_lock():
            self._ensure_started()
            assert self._response_queue is not None
            self._drain_response_queue()
            batch_id = uuid.uuid4().hex
            iterator = iter(specs)
            pending: set[int] = set()
            order_by_id: dict[int, int] = {}
            worker_by_request_id: dict[int, int] = {}
            request_payload_by_id: dict[int, dict[str, Any]] = {}
            request_requeue_count_by_id: dict[int, int] = {}
            worker_loads: dict[int, int] = {index: 0 for index in range(len(self._processes))}
            exhausted = await self._enqueue_until_window(
                batch_id,
                iterator,
                pending,
                order_by_id,
                worker_by_request_id,
                request_payload_by_id,
                request_requeue_count_by_id,
                worker_loads,
            )

            while pending:
                got_response = False
                try:
                    worker_index, received_batch_id, request_id, response_data, error_data = await asyncio.to_thread(
                        self._response_queue.get,
                        True,
                        1.0,
                    )
                    got_response = True
                except queue.Empty:
                    pass

                if self._has_pending_on_dead_worker(pending, worker_by_request_id):
                    self._log(
                        "[进程运行器] 检测到子进程退出 - URL: - 状态: worker_dead 重试: 0/0 代理: 多进程"
                    )
                    failed_responses = await self._recover_dead_workers(
                        batch_id,
                        pending,
                        order_by_id,
                        worker_by_request_id,
                        request_payload_by_id,
                        request_requeue_count_by_id,
                        worker_loads,
                    )
                    for order_index, failed_request_id, failed_response in failed_responses:
                        yield order_index, failed_request_id, failed_response
                    if not exhausted:
                        exhausted = await self._enqueue_until_window(
                            batch_id,
                            iterator,
                            pending,
                            order_by_id,
                            worker_by_request_id,
                            request_payload_by_id,
                            request_requeue_count_by_id,
                            worker_loads,
                        )

                if not got_response:
                    continue
                if received_batch_id != batch_id:
                    self._log(
                        f"[进程运行器] 丢弃过期响应 - URL: - 状态: batch_mismatch 重试: 0/0 代理: 多进程"
                    )
                    continue
                if request_id not in pending:
                    continue
                pending.remove(request_id)
                worker_loads[worker_index] = max(0, worker_loads.get(worker_index, 0) - 1)
                worker_by_request_id.pop(request_id, None)
                request_payload_by_id.pop(request_id, None)
                request_requeue_count_by_id.pop(request_id, None)
                if not exhausted:
                    exhausted = await self._enqueue_until_window(
                        batch_id,
                        iterator,
                        pending,
                        order_by_id,
                        worker_by_request_id,
                        request_payload_by_id,
                        request_requeue_count_by_id,
                        worker_loads,
                    )
                yield (
                    order_by_id.get(request_id, request_id),
                    request_id,
                    _process_result_to_response(request_id, response_data, error_data),
                )

    async def _enqueue_until_window(
        self,
        batch_id: str,
        iterator: Any,
        pending: set[int],
        order_by_id: dict[int, int],
        worker_by_request_id: dict[int, int],
        request_payload_by_id: dict[int, dict[str, Any]],
        request_requeue_count_by_id: dict[int, int],
        worker_loads: dict[int, int],
    ) -> bool:
        """
        向子进程请求队列填充一个批次窗口。

        Args:
            batch_id (str): 当前批次标识。
            iterator (Any): 请求规格迭代器。
            pending (set[int]): 尚未返回的请求序号集合。
            order_by_id (dict[int, int]): 请求序号到投递顺序的映射。
            worker_by_request_id (dict[int, int]): 请求序号到子进程下标的映射。
            request_payload_by_id (dict[int, dict[str, Any]]): 请求序号到原始请求字典的映射。
            request_requeue_count_by_id (dict[int, int]): 请求序号到重投次数的映射。
            worker_loads (dict[int, int]): 每个子进程的当前负载。

        Returns:
            bool: 输入迭代器耗尽返回 True。
        """

        while len(pending) < self._stream_window_size():
            try:
                spec = next(iterator)
            except StopIteration:
                return True
            request_id = self._counter
            self._counter += 1
            request_spec = spec if isinstance(spec, RequestSpec) else RequestSpec.from_dict(spec)
            request_payload = request_spec.to_dict()
            worker_index = self._select_target_worker(worker_loads)
            if worker_index is None:
                self._restart_dead_workers()
                worker_index = self._select_target_worker(worker_loads)
                if worker_index is None:
                    raise ProxyClientError("没有可用的子进程工作者")
            order_by_id[request_id] = len(order_by_id)
            await asyncio.to_thread(self._request_queues[worker_index].put, (batch_id, request_id, request_payload))
            pending.add(request_id)
            worker_by_request_id[request_id] = worker_index
            request_payload_by_id[request_id] = request_payload
            request_requeue_count_by_id[request_id] = 0
            worker_loads[worker_index] = worker_loads.get(worker_index, 0) + 1
        return False

    def _stream_window_size(self) -> int:
        """
        返回跨进程流式请求的主进程投递窗口。
        Returns:
            int: 投递窗口大小。
        """

        return max(1, min(self.queue_size, self.process_count * 2))

    async def _recover_dead_workers(
        self,
        batch_id: str,
        pending: set[int],
        order_by_id: dict[int, int],
        worker_by_request_id: dict[int, int],
        request_payload_by_id: dict[int, dict[str, Any]],
        request_requeue_count_by_id: dict[int, int],
        worker_loads: dict[int, int],
    ) -> list[tuple[int, int, Response]]:
        """
        恢复死亡子进程并精确重投受影响的请求。

        Args:
            batch_id (str): 当前批次标识。
            pending (set[int]): 尚未返回的请求序号集合。
            order_by_id (dict[int, int]): 请求序号到投递顺序的映射。
            worker_by_request_id (dict[int, int]): 请求序号到子进程下标的映射。
            request_payload_by_id (dict[int, dict[str, Any]]): 请求序号到原始请求字典的映射。
            request_requeue_count_by_id (dict[int, int]): 请求序号到重投次数的映射。
            worker_loads (dict[int, int]): 每个子进程的当前负载。

        Returns:
            list[tuple[int, int, Response]]: 无法恢复时需要直接返回的失败响应列表。
        """

        recovered_outputs = self._drain_current_batch_results(
            batch_id,
            pending,
            order_by_id,
            worker_by_request_id,
            request_payload_by_id,
            request_requeue_count_by_id,
            worker_loads,
        )
        dead_indexes = self._dead_worker_indexes()
        if not dead_indexes:
            return recovered_outputs

        queued_payloads_by_worker: dict[int, list[tuple[str, int, dict[str, Any]]]] = {}
        for worker_index in dead_indexes:
            queued_payloads_by_worker[worker_index] = self._drain_dead_request_queue(worker_index)
            worker_loads[worker_index] = 0

        self._restart_dead_workers(dead_indexes)

        for worker_index in dead_indexes:
            affected_request_ids = [
                request_id
                for request_id in list(pending)
                if worker_by_request_id.get(request_id) == worker_index
            ]
            requeue_payloads: dict[int, dict[str, Any]] = {}

            for drained_batch_id, drained_request_id, drained_payload in queued_payloads_by_worker.get(worker_index, []):
                if drained_batch_id == batch_id and drained_request_id in affected_request_ids:
                    requeue_payloads[drained_request_id] = drained_payload
                else:
                    self._log(
                        f"[进程运行器] 丢弃死亡子进程残留请求 - URL: - 状态: stale_request 重试: 0/0 "
                        f"代理: 多进程 worker: {worker_index}"
                    )

            for request_id in affected_request_ids:
                payload = requeue_payloads.get(request_id, request_payload_by_id.get(request_id))
                if payload is None:
                    pending.remove(request_id)
                    worker_by_request_id.pop(request_id, None)
                    request_payload_by_id.pop(request_id, None)
                    request_requeue_count_by_id.pop(request_id, None)
                    recovered_outputs.append(
                        (
                            order_by_id.get(request_id, request_id),
                            request_id,
                            _process_result_to_response(
                                request_id,
                                None,
                                {
                                    "type": "WorkerProcessExited",
                                    "message": "子进程异常退出，且丢失了待恢复请求载荷",
                                    "request_tag": str(request_id),
                                },
                            ),
                        )
                    )
                    continue

                retry_count = request_requeue_count_by_id.get(request_id, 0) + 1
                request_requeue_count_by_id[request_id] = retry_count
                if retry_count > MAX_WORKER_REQUEUE_ATTEMPTS:
                    pending.remove(request_id)
                    worker_by_request_id.pop(request_id, None)
                    request_payload_by_id.pop(request_id, None)
                    request_requeue_count_by_id.pop(request_id, None)
                    recovered_outputs.append(
                        (
                            order_by_id.get(request_id, request_id),
                            request_id,
                            _process_result_to_response(
                                request_id,
                                None,
                                {
                                    "type": "WorkerProcessExited",
                                    "message": "子进程多次异常退出，请求超过最大重投次数",
                                    "request_tag": str(request_id),
                                },
                            ),
                        )
                    )
                    continue

                target_worker_index = self._select_target_worker(worker_loads)
                if target_worker_index is None:
                    pending.remove(request_id)
                    worker_by_request_id.pop(request_id, None)
                    request_payload_by_id.pop(request_id, None)
                    request_requeue_count_by_id.pop(request_id, None)
                    recovered_outputs.append(
                        (
                            order_by_id.get(request_id, request_id),
                            request_id,
                            _process_result_to_response(
                                request_id,
                                None,
                                {
                                    "type": "WorkerProcessExited",
                                    "message": "没有可用子进程承接重投请求",
                                    "request_tag": str(request_id),
                                },
                            ),
                        )
                    )
                    continue

                await asyncio.to_thread(
                    self._request_queues[target_worker_index].put,
                    (batch_id, request_id, payload),
                )
                worker_by_request_id[request_id] = target_worker_index
                request_payload_by_id[request_id] = payload
                worker_loads[target_worker_index] = worker_loads.get(target_worker_index, 0) + 1
                self._log(
                    f"[进程运行器] 重投请求 - URL: - 状态: requeued 重试: {retry_count}/{MAX_WORKER_REQUEUE_ATTEMPTS} "
                    f"代理: 多进程 request_id: {request_id} worker: {target_worker_index}"
                )

        return recovered_outputs

    def _select_target_worker(self, worker_loads: dict[int, int]) -> int | None:
        """
        选择一个可用子进程承接请求。

        Args:
            worker_loads (dict[int, int]): 每个子进程的当前负载。

        Returns:
            int | None: 子进程下标；没有可用子进程时返回 None。
        """

        available_indexes = [
            index
            for index, process in enumerate(self._processes)
            if process.is_alive()
        ]
        if not available_indexes:
            return None

        chosen_index = min(
            available_indexes,
            key=lambda index: (worker_loads.get(index, 0), (index - self._next_worker_index) % len(self._processes)),
        )
        self._next_worker_index = (chosen_index + 1) % len(self._processes)
        return chosen_index

    def _drain_dead_request_queue(self, worker_index: int) -> list[tuple[str, int, dict[str, Any]]]:
        """
        清空死亡子进程对应的请求队列，避免重启后重复消费旧请求。

        Args:
            worker_index (int): 子进程下标。

        Returns:
            list[tuple[str, int, dict[str, Any]]]: 被清空的请求载荷列表。
        """

        drained: list[tuple[str, int, dict[str, Any]]] = []
        request_queue = self._request_queues[worker_index]
        while True:
            try:
                payload = request_queue.get_nowait()
            except queue.Empty:
                break
            except (OSError, ValueError):
                break
            if payload is None:
                continue
            drained.append(payload)
        return drained

    def _drain_current_batch_results(
        self,
        batch_id: str,
        pending: set[int],
        order_by_id: dict[int, int],
        worker_by_request_id: dict[int, int],
        request_payload_by_id: dict[int, dict[str, Any]],
        request_requeue_count_by_id: dict[int, int],
        worker_loads: dict[int, int],
    ) -> list[tuple[int, int, Response]]:
        """
        在恢复死亡子进程前，先清理当前批次已经到达响应队列的结果。

        Args:
            batch_id (str): 当前批次标识。
            pending (set[int]): 尚未返回的请求序号集合。
            order_by_id (dict[int, int]): 请求序号到投递顺序的映射。
            worker_by_request_id (dict[int, int]): 请求序号到子进程下标的映射。
            request_payload_by_id (dict[int, dict[str, Any]]): 请求序号到原始请求字典的映射。
            request_requeue_count_by_id (dict[int, int]): 请求序号到重投次数的映射。
            worker_loads (dict[int, int]): 每个子进程的当前负载。

        Returns:
            list[tuple[int, int, Response]]: 已经到达且可以立即返回的响应列表。
        """

        if self._response_queue is None:
            return []

        outputs: list[tuple[int, int, Response]] = []
        while True:
            try:
                worker_index, received_batch_id, request_id, response_data, error_data = self._response_queue.get_nowait()
            except queue.Empty:
                break
            except (OSError, ValueError):
                break

            if received_batch_id != batch_id:
                self._log(
                    "[进程运行器] 丢弃恢复期过期响应 - URL: - 状态: batch_mismatch 重试: 0/0 代理: 多进程"
                )
                continue
            if request_id not in pending:
                continue

            pending.remove(request_id)
            worker_loads[worker_index] = max(0, worker_loads.get(worker_index, 0) - 1)
            worker_by_request_id.pop(request_id, None)
            request_payload_by_id.pop(request_id, None)
            request_requeue_count_by_id.pop(request_id, None)
            outputs.append(
                (
                    order_by_id.get(request_id, request_id),
                    request_id,
                    _process_result_to_response(request_id, response_data, error_data),
                )
            )

        return outputs

    def _drain_response_queue(self) -> None:
        """
        清理上一批残留响应，避免新批次被过期消息阻塞。

        Returns:
            None: 无返回值。
        """

        if self._response_queue is None:
            return
        drained = 0
        while True:
            try:
                self._response_queue.get_nowait()
                drained += 1
            except queue.Empty:
                break
            except (OSError, ValueError):
                break
        if drained:
            self._log(
                f"[进程运行器] 清理过期响应 - URL: - 状态: drained 重试: 0/0 代理: 多进程 数量: {drained}"
            )

    def _has_dead_worker(self) -> bool:
        """
        检测是否存在已经异常退出的子进程。

        Returns:
            bool: 存在死亡子进程返回 True。
        """

        if self._stopping:
            return False
        return bool(self._dead_worker_indexes())

    def _has_pending_on_dead_worker(
        self,
        pending: set[int],
        worker_by_request_id: dict[int, int],
    ) -> bool:
        """
        检测是否存在绑定到已死亡子进程的 pending 请求。

        Args:
            pending (set[int]): 尚未返回的请求序号集合。
            worker_by_request_id (dict[int, int]): 请求序号到子进程下标的映射。

        Returns:
            bool: 存在被阻塞的 pending 请求返回 True。
        """

        if self._stopping:
            return False
        dead_indexes = set(self._dead_worker_indexes())
        if not dead_indexes:
            return False
        for request_id in pending:
            if worker_by_request_id.get(request_id) in dead_indexes:
                return True
        return False

    def _dead_worker_indexes(self) -> list[int]:
        """
        返回已经退出的子进程下标列表。

        Returns:
            list[int]: 已退出子进程下标列表。
        """

        if self._stopping:
            return []
        return [
            index
            for index, process in enumerate(self._processes)
            if (not process.is_alive()) and process.exitcode is not None
        ]

    def _restart_dead_workers(self, dead_indexes: list[int] | None = None) -> None:
        """
        重启已经退出的子进程，保证后续批次仍可继续运行。

        Args:
            dead_indexes (list[int] | None): 待重启的子进程下标列表；为空时自动探测。

        Returns:
            None: 无返回值。
        """

        if self._response_queue is None or self._stopping:
            return
        indexes = dead_indexes if dead_indexes is not None else self._dead_worker_indexes()
        for index in indexes:
            process = self._processes[index]
            if process.is_alive() or process.exitcode is None:
                continue
            try:
                process.join(timeout=0)
            except (OSError, ValueError):
                pass
            self._start_worker(index)
            self._log(
                f"[进程运行器] 重启子进程 - URL: - 状态: restarted 重试: 0/0 代理: 多进程 index: {index}"
            )

    def _start_worker(self, worker_index: int) -> None:
        """
        启动指定下标的子进程工作者。

        Args:
            worker_index (int): 子进程下标。

        Returns:
            None: 无返回值。
        """

        process = self._ctx.Process(
            target=_process_worker_entry,
            args=(
                worker_index,
                self.worker_factory,
                self._request_queues[worker_index],
                self._response_queue,
            ),
            name=f"ipweb-proxy-worker-{worker_index}",
        )
        process.start()
        if worker_index < len(self._processes):
            self._processes[worker_index] = process
        else:
            self._processes.append(process)

    def _ensure_started(self) -> None:
        """
        确保运行器已经启动。

        Returns:
            None: 无返回值。
        """

        if not self._started:
            self.start()

    def _get_stream_lock(self) -> asyncio.Lock:
        """
        延迟创建当前事件循环内的流式批次锁。

        Returns:
            asyncio.Lock: 批次锁。
        """

        if self._stream_lock is None:
            self._stream_lock = asyncio.Lock()
        return self._stream_lock

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


def _process_result_to_response(
    request_id: int,
    response_data: dict[str, Any] | None,
    error_data: dict[str, Any] | None,
) -> Response:
    """
    将子进程结果转换为响应对象。

    Args:
        request_id (int): 请求序号。
        response_data (dict[str, Any] | None): 响应字典。
        error_data (dict[str, Any] | None): 错误字典。

    Returns:
        Response: 响应对象。
    """

    if response_data is not None:
        response = Response.from_dict(response_data)
        if not response.request_tag:
            response.request_tag = str(request_id)
        return response

    error = ProxyClientError(
        str((error_data or {}).get("message", "")),
        request_tag=(error_data or {}).get("request_tag"),
        detail={"type": (error_data or {}).get("type", "UnknownError")},
    )
    return Response(
        status=None,
        headers=Headers(),
        url="",
        final_url="",
        method="",
        elapsed_ms=0.0,
        request_tag=str(request_id),
        error=error,
    )


def _response_to_process_dict(response: Response) -> dict[str, Any]:
    """
    将响应转换为跨进程安全字典。

    Args:
        response (Response): 响应对象。

    Returns:
        dict[str, Any]: 响应字典。
    """

    if response.content_path:
        try:
            response.content = response.body()
        except OSError as exc:
            raise ProxyClientError(
                f"读取落盘响应失败: {exc}",
                detail={"type": type(exc).__name__},
            ) from exc
        response.close()
    return response.to_dict()


__all__ = ["ProcessPoolRunner"]
