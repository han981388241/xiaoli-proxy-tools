"""
通用异步代理客户端。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import random
from typing import Any
from urllib.parse import urlsplit

from curl_cffi import requests

__all__ = [
    "AsyncProxyClient",
    "async_requests_request_retry",
]


class AsyncProxyClient:
    """
    基于 curl_cffi.AsyncSession 的通用异步代理客户端。

    说明:
        1. 默认使用异步请求。
        2. 请求参数会尽量透传给 curl_cffi。
        3. 返回值保持为 curl_cffi.requests.Response。
        4. 代理支持固定字符串、代理字典、PreparedProxy 对象、同步/异步代理提供器。
    """

    def __init__(
        self,
        *,
        session: Any | None = None,
        proxy_source: Any = None,
        retry_count: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 10.0,
        retry_statuses: tuple[int, ...] = (403, 429, 500, 502, 503, 504),
        rotate_proxy_on_retry: bool = True,
        verbose: bool = True,
        max_clients: int = 100,
        **session_kwargs: Any,
    ) -> None:
        """
        初始化通用异步代理客户端。

        Args:
            session (Any | None): 外部传入的异步 Session，对象需具备 request 方法。
            proxy_source (Any): 默认代理来源，可为字符串、字典、PreparedProxy、同步函数、异步函数。
            retry_count (int): 默认最大重试次数，最小为 1。
            base_delay (float): 指数退避基础等待秒数。
            max_delay (float): 单次最大等待秒数。
            retry_statuses (tuple[int, ...]): 需要触发重试的状态码集合。
            rotate_proxy_on_retry (bool): 重试时是否重新获取代理，仅对可调用代理来源生效。
            verbose (bool): 是否输出中文调试日志。
            max_clients (int): AsyncSession 内部并发连接上限。
            **session_kwargs (Any): 透传给 curl_cffi.requests.AsyncSession 的初始化参数。

        Returns:
            None: 无返回值。

        Raises:
            ValueError: 当同时传入外部 session 和 session_kwargs 时抛出。
        """

        if session is not None and session_kwargs:
            raise ValueError("session and session_kwargs cannot be used together")

        self._session = session or requests.AsyncSession(
            max_clients=max_clients,
            **session_kwargs,
        )
        self._owns_session = session is None
        self.proxy_source = proxy_source
        self.retry_count = max(1, int(retry_count))
        self.base_delay = float(base_delay)
        self.max_delay = float(max_delay)
        self.retry_statuses = tuple(retry_statuses)
        self.rotate_proxy_on_retry = bool(rotate_proxy_on_retry)
        self.verbose = bool(verbose)

    async def __aenter__(self) -> "AsyncProxyClient":
        """
        进入异步上下文。

        Returns:
            AsyncProxyClient: 当前客户端实例。
        """

        return self

    async def __aexit__(self, *args: Any) -> None:
        """
        退出异步上下文并关闭内部会话。

        Args:
            *args (Any): 异步上下文管理器透传参数。

        Returns:
            None: 无返回值。
        """

        await self.close()

    async def close(self) -> None:
        """
        关闭内部 Session。

        Returns:
            None: 无返回值。
        """

        if self._owns_session and self._session is not None:
            await self._session.close()

    async def request(
        self,
        method: str,
        url: str,
        *,
        retry_count: int | None = None,
        base_delay: float | None = None,
        max_delay: float | None = None,
        retry_statuses: tuple[int, ...] | None = None,
        proxy_source: Any = None,
        rotate_proxy_on_retry: bool | None = None,
        verbose: bool | None = None,
        **request_kwargs: Any,
    ) -> requests.Response:
        """
        发起异步请求并在需要时自动重试。

        Args:
            method (str): 请求方法，例如 GET、POST。
            url (str): 目标请求地址。
            retry_count (int | None): 本次请求覆盖默认重试次数。
            base_delay (float | None): 本次请求覆盖默认基础退避秒数。
            max_delay (float | None): 本次请求覆盖默认最大等待秒数。
            retry_statuses (tuple[int, ...] | None): 本次请求覆盖默认重试状态码。
            proxy_source (Any): 本次请求覆盖默认代理来源。
            rotate_proxy_on_retry (bool | None): 本次请求覆盖默认重试切换代理策略。
            verbose (bool | None): 本次请求覆盖默认日志输出策略。
            **request_kwargs (Any): 其余参数会透传给 curl_cffi.AsyncSession.request。

        Returns:
            requests.Response: curl_cffi 原生响应对象。

        Raises:
            Exception: 请求全量失败时抛出最后一次异常。
            TypeError: 代理来源格式不合法时抛出。
        """

        # =========================
        # 1. 构建请求参数
        # 2. 解析代理配置
        # 3. 发起请求
        # 4. 处理重试
        # 5. 返回结果
        # =========================
        method = (method or "GET").upper()
        final_retry_count = max(
            1,
            int(self.retry_count if retry_count is None else retry_count),
        )
        final_base_delay = float(base_delay if base_delay is not None else self.base_delay)
        final_max_delay = float(max_delay if max_delay is not None else self.max_delay)
        final_retry_statuses = (
            self.retry_statuses if retry_statuses is None else tuple(retry_statuses)
        )
        final_rotate_proxy = (
            self.rotate_proxy_on_retry
            if rotate_proxy_on_retry is None
            else bool(rotate_proxy_on_retry)
        )
        final_verbose = self.verbose if verbose is None else bool(verbose)

        fixed_proxy_kwargs: dict[str, Any] = {}
        resolved_proxy_source = proxy_source if proxy_source is not None else self.proxy_source
        request_payload = dict(request_kwargs)
        explicit_proxy_kwargs = self._extract_explicit_proxy_kwargs(request_payload)
        request_payload.pop("proxy", None)
        request_payload.pop("proxies", None)
        last_response: requests.Response | None = None
        last_exception: Exception | None = None

        if explicit_proxy_kwargs:
            fixed_proxy_kwargs = explicit_proxy_kwargs
        elif resolved_proxy_source is not None and (
            not callable(resolved_proxy_source) or not final_rotate_proxy
        ):
            fixed_proxy_kwargs = await self._resolve_proxy_source(resolved_proxy_source)

        for attempt in range(1, final_retry_count + 1):
            current_proxy_kwargs = fixed_proxy_kwargs
            current_status: int | None = None

            try:
                if (
                    not explicit_proxy_kwargs
                    and resolved_proxy_source is not None
                    and callable(resolved_proxy_source)
                    and final_rotate_proxy
                ):
                    current_proxy_kwargs = await self._resolve_proxy_source(resolved_proxy_source)

                current_proxy_text = self._format_proxy_for_log(current_proxy_kwargs)
                merged_request_kwargs = dict(request_payload)
                merged_request_kwargs.update(current_proxy_kwargs)

                self._log(
                    (
                        f"[代理客户端] 开始请求 - URL: {url} 方法: {method} "
                        f"重试: {attempt}/{final_retry_count} 代理: {current_proxy_text}"
                    ),
                    final_verbose,
                )

                last_response = await self._session.request(
                    method,
                    url,
                    **merged_request_kwargs,
                )
                current_status = getattr(last_response, "status_code", None)
                success = bool(current_status is not None and 200 <= current_status < 400)

                self._log(
                    (
                        f"[代理客户端] 请求完成 - URL: {url} 状态: {current_status} "
                        f"成功: {success} 重试: {attempt}/{final_retry_count} 代理: {current_proxy_text}"
                    ),
                    final_verbose,
                )

                if current_status not in final_retry_statuses:
                    return last_response

                self._log(
                    (
                        f"[代理客户端] 命中重试状态 - URL: {url} 状态: {current_status} "
                        f"重试: {attempt}/{final_retry_count} 代理: {current_proxy_text}"
                    ),
                    final_verbose,
                )
            except Exception as exc:
                last_exception = exc
                current_proxy_text = self._format_proxy_for_log(current_proxy_kwargs)
                self._log(
                    (
                        f"[代理客户端] 请求异常 - URL: {url} 状态: {current_status} "
                        f"重试: {attempt}/{final_retry_count} 代理: {current_proxy_text} "
                        f"错误: {repr(exc)}"
                    ),
                    final_verbose,
                )

            if attempt >= final_retry_count:
                break

            delay = min(final_max_delay, final_base_delay * (2 ** (attempt - 1)))
            delay += random.uniform(0.0, 0.3)
            self._log(
                (
                    f"[代理客户端] 等待重试 - URL: {url} 状态: {current_status} "
                    f"重试: {attempt}/{final_retry_count} 代理: "
                    f"{self._format_proxy_for_log(current_proxy_kwargs)} 延迟: {delay:.2f}s"
                ),
                final_verbose,
            )
            await asyncio.sleep(delay)

        if last_response is not None:
            return last_response

        if last_exception is not None:
            raise last_exception

        raise RuntimeError(f"request failed without response: {method} {url}")

    async def get(self, url: str, **kwargs: Any) -> requests.Response:
        """
        发起 GET 请求。

        Args:
            url (str): 目标请求地址。
            **kwargs (Any): 透传给 request 方法。

        Returns:
            requests.Response: curl_cffi 原生响应对象。
        """

        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> requests.Response:
        """
        发起 POST 请求。

        Args:
            url (str): 目标请求地址。
            **kwargs (Any): 透传给 request 方法。

        Returns:
            requests.Response: curl_cffi 原生响应对象。
        """

        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> requests.Response:
        """
        发起 PUT 请求。

        Args:
            url (str): 目标请求地址。
            **kwargs (Any): 透传给 request 方法。

        Returns:
            requests.Response: curl_cffi 原生响应对象。
        """

        return await self.request("PUT", url, **kwargs)

    async def patch(self, url: str, **kwargs: Any) -> requests.Response:
        """
        发起 PATCH 请求。

        Args:
            url (str): 目标请求地址。
            **kwargs (Any): 透传给 request 方法。

        Returns:
            requests.Response: curl_cffi 原生响应对象。
        """

        return await self.request("PATCH", url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> requests.Response:
        """
        发起 DELETE 请求。

        Args:
            url (str): 目标请求地址。
            **kwargs (Any): 透传给 request 方法。

        Returns:
            requests.Response: curl_cffi 原生响应对象。
        """

        return await self.request("DELETE", url, **kwargs)

    async def head(self, url: str, **kwargs: Any) -> requests.Response:
        """
        发起 HEAD 请求。

        Args:
            url (str): 目标请求地址。
            **kwargs (Any): 透传给 request 方法。

        Returns:
            requests.Response: curl_cffi 原生响应对象。
        """

        return await self.request("HEAD", url, **kwargs)

    async def options(self, url: str, **kwargs: Any) -> requests.Response:
        """
        发起 OPTIONS 请求。

        Args:
            url (str): 目标请求地址。
            **kwargs (Any): 透传给 request 方法。

        Returns:
            requests.Response: curl_cffi 原生响应对象。
        """

        return await self.request("OPTIONS", url, **kwargs)

    def _log(self, message: str, enabled: bool) -> None:
        """
        输出中文调试日志。

        Args:
            message (str): 日志文本。
            enabled (bool): 是否启用日志。

        Returns:
            None: 无返回值。
        """

        if enabled:
            print(message)

    def _extract_explicit_proxy_kwargs(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        """
        从请求参数中提取显式代理配置。

        Args:
            request_payload (dict[str, Any]): 原始请求参数字典。

        Returns:
            dict[str, Any]: 标准化后的代理参数字典。
        """

        result: dict[str, Any] = {}

        if request_payload.get("proxy") is not None:
            result["proxy"] = request_payload["proxy"]

        if request_payload.get("proxies") is not None:
            result["proxies"] = request_payload["proxies"]

        return result

    async def _resolve_proxy_source(self, proxy_source: Any) -> dict[str, Any]:
        """
        解析代理来源并转换为 curl_cffi 可识别的参数。

        Args:
            proxy_source (Any): 代理来源。

        Returns:
            dict[str, Any]: 可直接传入 request 的代理参数。

        Raises:
            TypeError: 当代理来源格式不支持时抛出。
        """

        resolved_value = proxy_source
        if callable(proxy_source):
            resolved_value = proxy_source()
            if inspect.isawaitable(resolved_value):
                resolved_value = await resolved_value

        if resolved_value is None:
            return {}

        if isinstance(resolved_value, str):
            return {"proxy": resolved_value}

        if isinstance(resolved_value, dict):
            if "proxy" in resolved_value or "proxies" in resolved_value:
                return dict(resolved_value)
            return {"proxies": dict(resolved_value)}

        if hasattr(resolved_value, "proxy_url") and isinstance(
            getattr(resolved_value, "proxy_url"),
            str,
        ):
            return {"proxy": getattr(resolved_value, "proxy_url")}

        if hasattr(resolved_value, "proxies") and isinstance(
            getattr(resolved_value, "proxies"),
            dict,
        ):
            return {"proxies": dict(getattr(resolved_value, "proxies"))}

        raise TypeError(
            "unsupported proxy_source type, expected str/dict/PreparedProxy/callable"
        )

    def _format_proxy_for_log(self, proxy_kwargs: dict[str, Any]) -> str:
        """
        生成脱敏后的代理日志文本。

        Args:
            proxy_kwargs (dict[str, Any]): 代理参数字典。

        Returns:
            str: 可直接输出的脱敏日志文本。
        """

        if not proxy_kwargs:
            return "直连"

        if isinstance(proxy_kwargs.get("proxy"), str):
            return self._mask_proxy_url(proxy_kwargs["proxy"])

        if isinstance(proxy_kwargs.get("proxies"), dict):
            masked_dict: dict[str, str] = {}
            for key, value in proxy_kwargs["proxies"].items():
                masked_dict[str(key)] = (
                    self._mask_proxy_url(value)
                    if isinstance(value, str)
                    else str(value)
                )
            return json.dumps(masked_dict, ensure_ascii=False)

        return "代理格式未知"

    def _mask_proxy_url(self, proxy_url: str) -> str:
        """
        对代理地址中的敏感认证信息进行脱敏。

        Args:
            proxy_url (str): 原始代理地址。

        Returns:
            str: 脱敏后的代理地址。
        """

        try:
            parsed = urlsplit(proxy_url)
        except Exception:
            return "***"

        if not parsed.scheme or not parsed.hostname:
            return "***"

        host_text = parsed.hostname
        if parsed.port is not None:
            host_text = f"{host_text}:{parsed.port}"

        if parsed.username or parsed.password:
            return f"{parsed.scheme}://***:***@{host_text}"

        return f"{parsed.scheme}://{host_text}"


async def async_requests_request_retry(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    proxies: dict[str, str] | None = None,
    proxy: str | None = None,
    params: dict[str, Any] | None = None,
    data: Any = None,
    json: Any = None,
    timeout: int | float = 60,
    verify: bool | None = False,
    impersonate: str | None = None,
    max_retries: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 15.0,
    retry_statuses: tuple[int, ...] = (403, 429, 500, 502, 503, 504),
    verbose: bool = True,
    proxy_source: Any = None,
    session: Any | None = None,
    **request_kwargs: Any,
) -> requests.Response:
    """
    兼容旧调用方式的异步重试请求封装。

    Args:
        method (str): 请求方法。
        url (str): 目标请求地址。
        headers (dict[str, str] | None): 请求头。
        cookies (dict[str, str] | None): Cookies。
        proxies (dict[str, str] | None): curl_cffi 支持的代理字典。
        proxy (str | None): 单代理地址。
        params (dict[str, Any] | None): 查询参数。
        data (Any): 表单或二进制数据。
        json (Any): JSON 请求体。
        timeout (int | float): 超时时间。
        verify (bool | None): 是否校验证书。
        impersonate (str | None): curl_cffi 指纹模拟参数。
        max_retries (int): 最大重试次数。
        base_delay (float): 基础退避秒数。
        max_delay (float): 最大退避秒数。
        retry_statuses (tuple[int, ...]): 触发重试的状态码集合。
        verbose (bool): 是否输出日志。
        proxy_source (Any): 默认代理来源。
        session (Any | None): 外部传入 Session。
        **request_kwargs (Any): 其余参数透传给 curl_cffi。

    Returns:
        requests.Response: curl_cffi 原生响应对象。
    """

    client = AsyncProxyClient(
        session=session,
        proxy_source=proxy_source,
        retry_count=max_retries,
        base_delay=base_delay,
        max_delay=max_delay,
        retry_statuses=retry_statuses,
        verbose=verbose,
    )
    try:
        merged_request_kwargs = dict(request_kwargs)
        merged_request_kwargs.update(
            {
                "headers": headers,
                "cookies": cookies,
                "params": params,
                "data": data,
                "json": json,
                "timeout": timeout,
                "verify": verify,
                "impersonate": impersonate,
            }
        )

        if proxy is not None:
            merged_request_kwargs["proxy"] = proxy
        if proxies is not None:
            merged_request_kwargs["proxies"] = proxies

        return await client.request(method, url, **merged_request_kwargs)
    finally:
        await client.close()


async def main() -> None:
    """
    模块直运行时的演示入口。

    Returns:
        None: 无返回值。
    """

    print("[示例入口] 已加载通用异步代理客户端 - 类名: AsyncProxyClient")
    print("[示例入口] 当前 main() 不发起真实网络请求，请在业务代码中按需调用")


if __name__ == "__main__":
    asyncio.run(main())
