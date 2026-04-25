"""
通用异步代理请求客户端。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from pathlib import Path
from typing import Any, AsyncIterator, Iterable, Iterator
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from .errors import ClientClosedError, ProxyClientError
from .limits import Limits
from .metrics import ClientMetrics
from .request import RequestSpec
from .response import Headers, Response
from .session import CookieRecord, SessionState
from .transport import AiohttpTransport, Transport

_LOGGER = logging.getLogger("proxy_scheduler_client")


class ProxyClient:
    """
    单代理单会话异步请求客户端。
    """

    def __init__(
        self,
        proxy_url: str | None = None,
        *,
        proxy_source: str | None = None,
        initial_state: SessionState | dict[str, Any] | None = None,
        limits: Limits | None = None,
        transport: Transport | None = None,
        trust_env: bool = False,
        verbose: bool = False,
        debug: bool = False,
        default_headers: dict[str, str] | None = None,
        user_agent: str = "",
        proxy_snapshot: str | None = None,
    ) -> None:
        """
        初始化异步代理客户端。

        Args:
            proxy_url (str | None): 代理地址，支持 http、https、socks5、socks5h。
            proxy_source (str | None): 代理地址别名参数，便于兼容外部命名。
            initial_state (SessionState | dict[str, Any] | None): 初始会话状态。
            limits (Limits | None): 并发、连接池和超时限制。
            transport (Transport | None): 自定义传输层。
            trust_env (bool): 是否读取系统环境代理。
            verbose (bool): 是否打印中文调试日志。
            debug (bool): 是否开启调试检查。
            default_headers (dict[str, str] | None): 默认请求头。
            user_agent (str): 默认 User-Agent。
            proxy_snapshot (str | None): 外部传入的脱敏代理快照。

        Returns:
            None: 无返回值。

        Raises:
            ValueError: 代理地址缺失或重复传入时抛出。
        """

        if proxy_url and proxy_source and proxy_url != proxy_source:
            raise ValueError("proxy_url and proxy_source cannot point to different proxies")
        resolved_proxy = proxy_url or proxy_source
        if not resolved_proxy:
            raise ValueError("proxy_url is required")

        self._proxy_url = resolved_proxy
        self.limits = limits or Limits()
        self.verbose = verbose
        self.debug = debug
        self.metrics = ClientMetrics()
        self._closed = False
        self._semaphore: asyncio.Semaphore | None = None
        self._state = self._build_state(initial_state)
        self._state.proxy_hint = proxy_snapshot or _mask_proxy_url(self._proxy_url)
        self._state.source_proxy_fingerprint = _fingerprint_proxy_url(self._proxy_url)
        if default_headers:
            self._state.default_headers.update(default_headers)
        if user_agent:
            self._state.user_agent = user_agent

        self._transport = transport or AiohttpTransport(
            proxy_url=self._proxy_url,
            limits=self.limits,
            proxy_snapshot=self.current_proxy_masked(),
            trust_env=trust_env,
        )
        if self._state.cookies:
            self._transport.import_cookies(self._state.cookies, merge=True)

    @property
    def is_closed(self) -> bool:
        """
        返回客户端是否已经关闭。

        Returns:
            bool: 已关闭返回 True。
        """

        return self._closed

    @property
    def state(self) -> SessionState:
        """
        返回会话状态快照。

        Returns:
            SessionState: 深拷贝后的会话状态对象。
        """

        return self.export_state()

    async def __aenter__(self) -> "ProxyClient":
        """
        进入异步上下文。

        Returns:
            ProxyClient: 当前客户端实例。
        """

        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        """
        退出异步上下文并关闭资源。

        Args:
            exc_type (Any): 异常类型。
            exc (Any): 异常对象。
            traceback (Any): 异常堆栈。

        Returns:
            None: 无返回值。
        """

        await self.close()

    async def request(
        self,
        method: str | RequestSpec | dict[str, Any],
        url: str | None = None,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        data: Any = None,
        json: Any = None,
        timeout: float | None = None,
        tag: str | None = None,
        meta: dict[str, Any] | None = None,
        return_exceptions: bool = False,
        **options: Any,
    ) -> Response:
        """
        执行单个异步请求。

        Args:
            method (str | RequestSpec | dict[str, Any]): HTTP 方法或请求规格。
            url (str | None): 请求 URL。
            headers (dict[str, str] | None): 请求头。
            params (dict[str, Any] | None): 查询参数。
            data (Any): 表单或原始请求体。
            json (Any): JSON 请求体。
            timeout (float | None): 单请求总超时时间。
            tag (str | None): 请求标签。
            meta (dict[str, Any] | None): 自定义上下文。
            return_exceptions (bool): 是否把异常包装进 Response。
            **options (Any): 额外请求选项，会写入 RequestSpec.meta。

        Returns:
            Response: 响应对象。

        Raises:
            ProxyClientError: 请求失败且 return_exceptions 为 False 时抛出。
        """

        spec = self._build_spec(
            method,
            url,
            headers=headers,
            params=params,
            data=data,
            json=json,
            timeout=timeout,
            tag=tag,
            meta=meta,
            options=options,
        )
        if self._closed:
            error = ClientClosedError(
                "客户端已经关闭",
                proxy_snapshot=self.current_proxy_masked(),
                request_tag=spec.tag,
            )
            if return_exceptions:
                return self._error_response(spec, error, 0.0)
            raise error

        return await self._request_limited(spec, return_exceptions)

    def request_to_curl(
        self,
        method: str | RequestSpec | dict[str, Any],
        url: str | None = None,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        data: Any = None,
        json: Any = None,
        timeout: float | None = None,
        tag: str | None = None,
        meta: dict[str, Any] | None = None,
        pretty: bool = False,
        masked: bool = False,
        shell: str = "auto",
        **options: Any,
    ) -> str:
        """
        将当前客户端即将发出的请求导出为 curl 命令。

        Args:
            method (str | RequestSpec | dict[str, Any]): HTTP 方法或请求规格。
            url (str | None): 请求 URL。
            headers (dict[str, str] | None): 请求头。
            params (dict[str, Any] | None): 查询参数。
            data (Any): 表单或原始请求体。
            json (Any): JSON 请求体。
            timeout (float | None): 单请求总超时时间。
            tag (str | None): 请求标签。
            meta (dict[str, Any] | None): 自定义上下文。
            pretty (bool): 是否输出适合终端阅读的多行命令。
            masked (bool): 是否对敏感信息脱敏。
            shell (str): 目标终端类型，支持 auto、bash、powershell 和 cmd。
            **options (Any): 额外请求选项，会写入 RequestSpec.meta。

        Returns:
            str: curl 命令字符串。
        """

        spec = self._build_spec(
            method,
            url,
            headers=headers,
            params=params,
            data=data,
            json=json,
            timeout=timeout,
            tag=tag,
            meta=meta,
            options=options,
        )

        merged_headers: dict[str, str] = {}
        merged_headers.update(self._state.default_headers)
        merged_headers.update(self._state.headers_sticky)
        if self._state.user_agent and not _contains_header(merged_headers, "User-Agent"):
            merged_headers["User-Agent"] = self._state.user_agent
        if spec.headers:
            merged_headers.update({str(key): str(value) for key, value in spec.headers.items()})

        effective_timeout = spec.timeout if spec.timeout is not None else self.limits.total_timeout
        final_spec = RequestSpec(
            method=spec.method,
            url=spec.url,
            headers=merged_headers,
            params=spec.params,
            data=spec.data,
            json=spec.json,
            timeout=effective_timeout,
            tag=spec.tag,
            meta=dict(spec.meta),
        )
        cookie_mapping = _cookies_for_url(self._state.cookies, spec.url)
        return final_spec.to_curl(
            pretty=pretty,
            masked=masked,
            shell=shell,
            proxy_url=self._proxy_url,
            cookies=cookie_mapping,
            connect_timeout=self.limits.connect_timeout,
        )

    async def _request_limited(self, spec: RequestSpec, return_exceptions: bool) -> Response:
        """
        在统一并发限制内执行单个请求。

        Args:
            spec (RequestSpec): 请求规格。
            return_exceptions (bool): 是否把异常包装进 Response。

        Returns:
            Response: 响应对象。
        """

        semaphore = self._get_semaphore()
        async with semaphore:
            return await self._request_once(spec, return_exceptions)

    async def _request_once(self, spec: RequestSpec, return_exceptions: bool) -> Response:
        """
        执行单个请求的底层路径。

        Args:
            spec (RequestSpec): 请求规格。
            return_exceptions (bool): 是否把异常包装进 Response。

        Returns:
            Response: 响应对象。

        Raises:
            ProxyClientError: 请求失败且 return_exceptions 为 False 时抛出。
        """

        started = time.perf_counter()
        self.metrics.start()
        if self.verbose:
            self._log(
                f"[代理客户端] 开始请求 - URL: {spec.url} 方法: {spec.method.upper()} "
                f"重试: 1/1 代理: {self.current_proxy_masked()}"
            )

        try:
            response = await self._transport.request(spec, self._state)
            self.metrics.complete(
                elapsed_ms=response.elapsed_ms,
                bytes_received=_response_size(response),
            )
            if self.verbose:
                self._log(
                    f"[代理客户端] 请求完成 - URL: {spec.url} 状态: {response.status} "
                    f"成功: {response.ok} 重试: 1/1 代理: {self.current_proxy_masked()}"
                )
            return response
        except ProxyClientError as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000
            self.metrics.fail(elapsed_ms=elapsed_ms)
            if self.verbose:
                self._log(
                    f"[代理客户端] 请求失败 - URL: {spec.url} 状态: None 重试: 1/1 "
                    f"代理: {self.current_proxy_masked()} 错误: {type(exc).__name__}: {exc}"
                )
            if return_exceptions:
                return self._error_response(spec, exc, elapsed_ms)
            raise
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000
            error = ProxyClientError(
                str(exc),
                proxy_snapshot=self.current_proxy_masked(),
                request_tag=spec.tag,
                detail={"type": type(exc).__name__},
            )
            self.metrics.fail(elapsed_ms=elapsed_ms)
            if self.verbose:
                self._log(
                    f"[代理客户端] 请求失败 - URL: {spec.url} 状态: None 重试: 1/1 "
                    f"代理: {self.current_proxy_masked()} 错误: {type(exc).__name__}: {exc}"
                )
            if return_exceptions:
                return self._error_response(spec, error, elapsed_ms)
            raise error from exc

    async def get(self, url: str, **kwargs: Any) -> Response:
        """
        发起 GET 请求。

        Args:
            url (str): 请求 URL。
            **kwargs (Any): 请求参数。

        Returns:
            Response: 响应对象。
        """

        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> Response:
        """
        发起 POST 请求。

        Args:
            url (str): 请求 URL。
            **kwargs (Any): 请求参数。

        Returns:
            Response: 响应对象。
        """

        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> Response:
        """
        发起 PUT 请求。

        Args:
            url (str): 请求 URL。
            **kwargs (Any): 请求参数。

        Returns:
            Response: 响应对象。
        """

        return await self.request("PUT", url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> Response:
        """
        发起 DELETE 请求。

        Args:
            url (str): 请求 URL。
            **kwargs (Any): 请求参数。

        Returns:
            Response: 响应对象。
        """

        return await self.request("DELETE", url, **kwargs)

    async def patch(self, url: str, **kwargs: Any) -> Response:
        """
        发起 PATCH 请求。

        Args:
            url (str): 请求 URL。
            **kwargs (Any): 请求参数。

        Returns:
            Response: 响应对象。
        """

        return await self.request("PATCH", url, **kwargs)

    async def head(self, url: str, **kwargs: Any) -> Response:
        """
        发起 HEAD 请求。

        Args:
            url (str): 请求 URL。
            **kwargs (Any): 请求参数。

        Returns:
            Response: 响应对象。
        """

        return await self.request("HEAD", url, **kwargs)

    async def options(self, url: str, **kwargs: Any) -> Response:
        """
        发起 OPTIONS 请求。

        Args:
            url (str): 请求 URL。
            **kwargs (Any): 请求参数。

        Returns:
            Response: 响应对象。
        """

        return await self.request("OPTIONS", url, **kwargs)

    async def stream(
        self,
        specs: Iterable[RequestSpec | dict[str, Any]],
        *,
        return_exceptions: bool = True,
    ) -> AsyncIterator[Response]:
        """
        以背压方式流式执行多请求。

        Args:
            specs (Iterable[RequestSpec | dict[str, Any]]): 请求规格迭代器。
            return_exceptions (bool): 是否把异常包装进 Response。

        Yields:
            Response: 响应对象。
        """

        iterator = iter(specs)
        pending: dict[asyncio.Future[Response], RequestSpec] = {}
        exhausted = False

        try:
            while len(pending) < self.limits.concurrency and not exhausted:
                exhausted, _ = self._fill_stream_one(iterator, pending, return_exceptions)
            while pending:
                done, _ = await asyncio.wait(
                    pending,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                first_error: BaseException | None = None
                for task in done:
                    spec = pending.pop(task)
                    try:
                        yield task.result()
                    except Exception as exc:
                        if not return_exceptions:
                            if first_error is None:
                                first_error = exc
                            continue
                        yield self._error_response(
                            spec,
                            ProxyClientError(
                                str(exc),
                                proxy_snapshot=self.current_proxy_masked(),
                                request_tag=spec.tag,
                                detail={"type": type(exc).__name__},
                            ),
                            0.0,
                        )
                if first_error is not None:
                    raise first_error
                for _ in done:
                    if not exhausted:
                        exhausted, _ = self._fill_stream_one(iterator, pending, return_exceptions)
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
        执行多请求并一次性返回响应列表。

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

    def export_state(self) -> SessionState:
        """
        导出会话状态快照。

        Returns:
            SessionState: 深拷贝后的会话状态。
        """

        self._sync_cookies_from_transport()
        return self._state.copy()

    async def import_state(self, state: SessionState | dict[str, Any], *, merge: bool = True) -> None:
        """
        导入会话状态快照。

        Args:
            state (SessionState | dict[str, Any]): 会话状态。
            merge (bool): 是否合并当前状态。

        Returns:
            None: 无返回值。
        """

        if merge:
            self._sync_cookies_from_transport()
        imported = self._build_state(state)
        if merge:
            self._state.cookies = _merge_cookie_records(self._state.cookies, imported.cookies)
            self._state.headers_sticky.update(imported.headers_sticky)
            self._state.default_headers.update(imported.default_headers)
            self._state.local_storage.update(imported.local_storage)
            self._state.user_agent = imported.user_agent or self._state.user_agent
        else:
            self._state = imported

        self._state.proxy_hint = self.current_proxy_masked()
        self._state.source_proxy_fingerprint = _fingerprint_proxy_url(self._proxy_url)
        self._transport.import_cookies(self._state.cookies, merge=merge)
        self._log(
            f"[代理客户端] 导入会话状态 - URL: - 状态: 完成 重试: 0/0 代理: {self.current_proxy_masked()}"
        )

    def get_cookies(self, domain: str | None = None) -> list[CookieRecord]:
        """
        获取当前 Cookie。

        Args:
            domain (str | None): 可选域名过滤。

        Returns:
            list[CookieRecord]: Cookie 列表。
        """

        self._sync_cookies_from_transport()
        if domain is None:
            return list(self._state.cookies)
        return [cookie for cookie in self._state.cookies if cookie.domain == domain]

    def set_cookie(self, cookie: CookieRecord) -> None:
        """
        写入单个 Cookie。

        Args:
            cookie (CookieRecord): Cookie 记录。

        Returns:
            None: 无返回值。
        """

        self._state.cookies = [
            item
            for item in self._state.cookies
            if not (item.name == cookie.name and item.domain == cookie.domain and item.path == cookie.path)
        ]
        self._state.cookies.append(cookie)
        self._transport.import_cookies([cookie], merge=True)

    def clear_cookies(self) -> None:
        """
        清空当前 Cookie。

        Returns:
            None: 无返回值。
        """

        self._state.cookies.clear()
        self._transport.import_cookies([], merge=False)

    def sticky_header(self, name: str, value: str) -> None:
        """
        设置会话级请求头。

        Args:
            name (str): 请求头名称。
            value (str): 请求头值。

        Returns:
            None: 无返回值。
        """

        self._state.headers_sticky[name] = value

    def unsticky_header(self, name: str) -> None:
        """
        删除会话级请求头。

        Args:
            name (str): 请求头名称。

        Returns:
            None: 无返回值。
        """

        self._state.headers_sticky.pop(name, None)

    def set_local(self, key: str, value: Any) -> None:
        """
        写入本地会话状态。

        Args:
            key (str): 状态键。
            value (Any): 状态值。

        Returns:
            None: 无返回值。
        """

        self._state.local_storage[key] = value

    def get_local(self, key: str, default: Any = None) -> Any:
        """
        读取本地会话状态。

        Args:
            key (str): 状态键。
            default (Any): 默认值。

        Returns:
            Any: 状态值。
        """

        return self._state.local_storage.get(key, default)

    def current_proxy_masked(self) -> str:
        """
        返回脱敏代理地址。

        Returns:
            str: 脱敏代理地址。
        """

        return _mask_proxy_url(self._proxy_url)

    def assert_isolated_from(self, other: "ProxyClient") -> None:
        """
        检查两个客户端是否没有共享会话对象。

        Args:
            other (ProxyClient): 另一个客户端。

        Returns:
            None: 无返回值。

        Raises:
            ProxyClientError: 检测到共享状态时抛出。
        """

        if self._state is other._state:
            raise ProxyClientError("两个 ProxyClient 共享了 SessionState")
        if self._transport is other._transport:
            raise ProxyClientError("两个 ProxyClient 共享了 Transport")
        if getattr(self._transport, "_cookie_jar", None) is not None and (
            getattr(self._transport, "_cookie_jar", None) is getattr(other._transport, "_cookie_jar", None)
        ):
            raise ProxyClientError("两个 ProxyClient 共享了 CookieJar")
        if getattr(self._transport, "_session", None) is not None and (
            getattr(self._transport, "_session", None) is getattr(other._transport, "_session", None)
        ):
            raise ProxyClientError("两个 ProxyClient 共享了 ClientSession")

    async def close(self) -> None:
        """
        关闭客户端资源。

        Returns:
            None: 无返回值。
        """

        if self._closed:
            return
        self._sync_cookies_from_transport()
        await self._transport.close()
        self._closed = True
        self._log(
            f"[代理客户端] 关闭客户端 - URL: - 状态: 完成 重试: 0/0 代理: {self.current_proxy_masked()}"
        )

    def _fill_stream_one(
        self,
        iterator: Iterator[RequestSpec | dict[str, Any]],
        pending: dict[asyncio.Future[Response], RequestSpec],
        return_exceptions: bool,
    ) -> tuple[bool, bool]:
        """
        为流式请求增量补充一个 in-flight 任务。

        Args:
            iterator (Iterator[RequestSpec | dict[str, Any]]): 请求规格迭代器。
            pending (dict[asyncio.Task[Response], RequestSpec]): 运行中的任务映射。
            return_exceptions (bool): 是否把异常包装进 Response。

        Returns:
            tuple[bool, bool]: 是否耗尽输入、是否成功补充任务。
        """

        try:
            spec = self._coerce_spec(next(iterator))
        except StopIteration:
            return True, False
        except Exception as exc:
            spec = RequestSpec(method="GET", url="", tag="input-error")
            response = self._error_response(
                spec,
                ProxyClientError(
                    str(exc),
                    proxy_snapshot=self.current_proxy_masked(),
                    request_tag=spec.tag,
                    detail={"type": type(exc).__name__},
                ),
                0.0,
            )
            task = _completed_response_task(response)
            pending[task] = spec
            return False, True

        task = asyncio.create_task(self._request_limited(spec, return_exceptions))
        pending[task] = spec
        return False, True

    def _get_semaphore(self) -> asyncio.Semaphore:
        """
        延迟创建当前事件循环内的并发信号量。

        Returns:
            asyncio.Semaphore: 并发信号量。
        """

        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.limits.concurrency)
        return self._semaphore

    def _build_spec(
        self,
        method: str | RequestSpec | dict[str, Any],
        url: str | None,
        *,
        headers: dict[str, str] | None,
        params: dict[str, Any] | None,
        data: Any,
        json: Any,
        timeout: float | None,
        tag: str | None,
        meta: dict[str, Any] | None,
        options: dict[str, Any],
    ) -> RequestSpec:
        """
        构造请求规格对象。

        Args:
            method (str | RequestSpec | dict[str, Any]): HTTP 方法或请求规格。
            url (str | None): 请求 URL。
            headers (dict[str, str] | None): 请求头。
            params (dict[str, Any] | None): 查询参数。
            data (Any): 表单或原始请求体。
            json (Any): JSON 请求体。
            timeout (float | None): 单请求总超时时间。
            tag (str | None): 请求标签。
            meta (dict[str, Any] | None): 自定义上下文。
            options (dict[str, Any]): 额外请求选项。

        Returns:
            RequestSpec: 请求规格。

        Raises:
            ValueError: 请求参数不完整时抛出。
        """

        if isinstance(method, RequestSpec):
            return method
        if isinstance(method, dict):
            return RequestSpec.from_dict(method)
        if not url:
            raise ValueError("url is required")
        merged_meta = dict(meta or {})
        merged_meta.update(options)
        return RequestSpec(
            method=method.upper(),
            url=url,
            headers=headers,
            params=params,
            data=data,
            json=json,
            timeout=timeout,
            tag=tag,
            meta=merged_meta,
        )

    def _coerce_spec(self, spec: RequestSpec | dict[str, Any]) -> RequestSpec:
        """
        规范化流式请求规格。

        Args:
            spec (RequestSpec | dict[str, Any]): 请求规格。

        Returns:
            RequestSpec: 请求规格对象。
        """

        if isinstance(spec, RequestSpec):
            return spec
        return RequestSpec.from_dict(spec)

    def _sync_cookies_from_transport(self) -> None:
        """
        从传输层同步 Cookie 到会话状态。

        Returns:
            None: 无返回值。
        """

        try:
            cookies = self._transport.export_cookies()
        except Exception as exc:
            self._log(
                f"[代理客户端] Cookie 同步失败 - URL: - 状态: ignored 重试: 0/0 "
                f"代理: {self.current_proxy_masked()} 错误: {type(exc).__name__}: {exc}"
            )
            return
        self._state.cookies = cookies

    def _error_response(self, spec: RequestSpec, error: ProxyClientError, elapsed_ms: float) -> Response:
        """
        构造失败响应对象。

        Args:
            spec (RequestSpec): 请求规格。
            error (ProxyClientError): 请求异常。
            elapsed_ms (float): 请求耗时。

        Returns:
            Response: 失败响应对象。
        """

        return Response(
            status=None,
            headers=Headers(),
            url=spec.url,
            final_url=spec.url,
            method=spec.method.upper(),
            elapsed_ms=elapsed_ms,
            request_tag=spec.tag,
            content=b"",
            content_path=None,
            encoding=None,
            proxy_snapshot=self.current_proxy_masked(),
            error=error,
            history=[],
        )

    def _build_state(self, state: SessionState | dict[str, Any] | None) -> SessionState:
        """
        构造内部会话状态。

        Args:
            state (SessionState | dict[str, Any] | None): 原始会话状态。

        Returns:
            SessionState: 会话状态对象。
        """

        if state is None:
            return SessionState()
        if isinstance(state, SessionState):
            return state.copy()
        return SessionState.from_dict(state)

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


def _mask_proxy_url(proxy_url: str) -> str:
    """
    脱敏代理地址中的认证信息。

    Args:
        proxy_url (str): 原始代理地址。

    Returns:
        str: 脱敏代理地址。
    """

    parsed = urlsplit(proxy_url)
    if not parsed.username and not parsed.password:
        return proxy_url

    username = unquote(parsed.username or "")
    masked_user = username[:2] + "***" if len(username) > 2 else "***"
    auth = quote(masked_user, safe="*_-.") + ":***@"
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, auth + host, parsed.path, parsed.query, parsed.fragment))


def _fingerprint_proxy_url(proxy_url: str) -> str:
    """
    生成代理地址指纹。

    Args:
        proxy_url (str): 原始代理地址。

    Returns:
        str: 短指纹。
    """

    return hashlib.sha256(proxy_url.encode("utf-8")).hexdigest()[:16]


def _response_size(response: Response) -> int:
    """
    计算响应体大小。

    Args:
        response (Response): 响应对象。

    Returns:
        int: 响应体字节数。
    """

    if response.content_path:
        try:
            return Path(response.content_path).stat().st_size
        except OSError:
            return 0
    return len(response.content)


def _contains_header(headers: dict[str, str], target_name: str) -> bool:
    """
    判断请求头映射中是否已存在指定名称。

    Args:
        headers (dict[str, str]): 请求头映射。
        target_name (str): 目标请求头名称。

    Returns:
        bool: 存在时返回 True。
    """

    lowered = target_name.lower()
    return any(str(name).lower() == lowered for name in headers)


def _cookies_for_url(cookies: list[CookieRecord], url: str) -> dict[str, str]:
    """
    按目标 URL 的域名和路径筛选当前会话 Cookie。

    Args:
        cookies (list[CookieRecord]): 当前会话 Cookie 列表。
        url (str): 目标请求 URL。

    Returns:
        dict[str, str]: 需要随请求发送的 Cookie 映射。
    """

    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path or "/"
    matched: dict[str, str] = {}

    for cookie in cookies:
        domain = str(cookie.domain or "").lstrip(".").lower()
        cookie_path = cookie.path or "/"
        if domain and host != domain and not host.endswith(f".{domain}"):
            continue
        if not path.startswith(cookie_path):
            continue
        matched[cookie.name] = cookie.value

    return matched


def _merge_cookie_records(
    current: list[CookieRecord],
    incoming: list[CookieRecord],
) -> list[CookieRecord]:
    """
    按 name、domain、path 合并 Cookie。

    Args:
        current (list[CookieRecord]): 当前 Cookie 列表。
        incoming (list[CookieRecord]): 待导入 Cookie 列表。

    Returns:
        list[CookieRecord]: 合并后的 Cookie 列表。
    """

    merged: dict[tuple[str, str, str], CookieRecord] = {}
    for cookie in current:
        merged[(cookie.name, cookie.domain, cookie.path)] = cookie
    for cookie in incoming:
        merged[(cookie.name, cookie.domain, cookie.path)] = cookie
    return list(merged.values())


def _completed_response_task(response: Response) -> asyncio.Future[Response]:
    """
    创建一个已经完成的响应任务。

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


__all__ = ["ProxyClient"]
