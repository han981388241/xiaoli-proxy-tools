"""
aiohttp 传输层实现。
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from email.utils import parsedate_to_datetime
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any

from ..errors import (
    ProtocolError,
    ProxyAuthError,
    ProxyConnectionError,
    ProxyTimeoutError,
    TargetConnectionError,
    TLSError,
)
from ..limits import Limits
from ..pool import build_connector, load_aiohttp
from ..request import RequestSpec
from ..response import Headers, RedirectRecord, Response
from ..session import CookieRecord, SessionState
from .base import Transport


class AiohttpTransport(Transport):
    """
    基于 aiohttp 的传输层实现。
    """

    def __init__(
        self,
        *,
        proxy_url: str,
        limits: Limits,
        proxy_snapshot: str,
        trust_env: bool = False,
    ) -> None:
        """
        初始化 aiohttp 传输层。

        Args:
            proxy_url (str): 真实代理地址。
            limits (Limits): 运行限制。
            proxy_snapshot (str): 脱敏代理标识。
            trust_env (bool): 是否读取系统环境代理。

        Returns:
            None: 无返回值。
        """

        self.proxy_url = proxy_url
        self.limits = limits
        self.proxy_snapshot = proxy_snapshot
        self.trust_env = trust_env
        self._aiohttp: Any | None = None
        self._session: Any | None = None
        self._connector: Any | None = None
        self._native_proxy: str | None = None
        self._cookie_jar: Any | None = None

    async def request(self, spec: RequestSpec, state: SessionState) -> Response:
        """
        执行单个 aiohttp 请求。

        Args:
            spec (RequestSpec): 请求规格。
            state (SessionState): 会话状态。

        Returns:
            Response: 响应对象。

        Raises:
            ProxyConnectionError: 代理连接失败时抛出。
            TargetConnectionError: 目标站连接失败时抛出。
            ProxyTimeoutError: 请求超时时抛出。
            ProtocolError: HTTP 协议异常时抛出。
        """

        session = await self._ensure_session(state)
        headers = self._build_headers(spec, state)
        timeout = self._build_timeout(spec)
        request_options = self._build_request_options(spec)
        started = time.perf_counter()

        try:
            async with session.request(
                spec.method.upper(),
                spec.url,
                headers=headers,
                params=spec.params,
                data=spec.data,
                json=spec.json,
                timeout=timeout,
                proxy=self._native_proxy,
                **request_options,
            ) as response:
                content, content_path = await self._read_response_body(response)
                elapsed_ms = (time.perf_counter() - started) * 1000
                history = [
                    RedirectRecord(status=item.status, url=str(item.url))
                    for item in response.history
                ]
                return Response(
                    status=response.status,
                    headers=Headers.from_mapping(response.headers),
                    url=spec.url,
                    final_url=str(response.url),
                    method=spec.method.upper(),
                    elapsed_ms=elapsed_ms,
                    request_tag=spec.tag,
                    content=content,
                    content_path=content_path,
                    encoding=response.charset,
                    proxy_snapshot=self.proxy_snapshot,
                    error=None,
                    history=history,
                )
        except (asyncio.TimeoutError, TimeoutError) as exc:
            raise ProxyTimeoutError(
                str(exc) or "request timeout",
                proxy_snapshot=self.proxy_snapshot,
                request_tag=spec.tag,
            ) from exc
        except Exception as exc:
            raise self._map_exception(exc, spec) from exc

    async def close(self) -> None:
        """
        关闭 aiohttp 会话和连接器。

        Returns:
            None: 无返回值。
        """

        if self._session is not None:
            await self._session.close()
            self._session = None
        self._connector = None

    def export_cookies(self) -> list[CookieRecord]:
        """
        导出 aiohttp CookieJar 中的 Cookie。

        Returns:
            list[CookieRecord]: Cookie 列表。
        """

        if self._cookie_jar is None:
            return []

        result: list[CookieRecord] = []
        for morsel in self._cookie_jar:
            result.append(
                CookieRecord(
                    name=morsel.key,
                    value=morsel.value,
                    domain=morsel["domain"] or "",
                    path=morsel["path"] or "/",
                    expires=_parse_cookie_expiry(morsel["expires"], morsel["max-age"]),
                    secure=bool(morsel["secure"]),
                    httponly=bool(morsel["httponly"]),
                    samesite=morsel["samesite"] or None,
                )
            )
        return result

    def import_cookies(self, cookies: list[CookieRecord], *, merge: bool = True) -> None:
        """
        导入 Cookie 到 aiohttp CookieJar。

        Args:
            cookies (list[CookieRecord]): Cookie 列表。
            merge (bool): 是否合并已有 Cookie。

        Returns:
            None: 无返回值。
        """

        aiohttp = load_aiohttp()
        if self._cookie_jar is None:
            self._cookie_jar = aiohttp.CookieJar(unsafe=True)
        elif not merge:
            self._cookie_jar.clear()

        for record in cookies:
            cookie = SimpleCookie()
            cookie[record.name] = record.value
            cookie[record.name]["path"] = record.path
            if record.domain:
                cookie[record.name]["domain"] = record.domain
            if record.secure:
                cookie[record.name]["secure"] = True
            if record.httponly:
                cookie[record.name]["httponly"] = True
            if record.samesite:
                cookie[record.name]["samesite"] = record.samesite
            self._cookie_jar.update_cookies(cookie)

    async def _ensure_session(self, state: SessionState) -> Any:
        """
        确保 aiohttp ClientSession 已初始化。

        Args:
            state (SessionState): 会话状态。

        Returns:
            Any: aiohttp ClientSession。
        """

        if self._session is not None:
            return self._session

        self._aiohttp = load_aiohttp()
        self._connector, self._native_proxy = build_connector(self.proxy_url, self.limits)
        self._cookie_jar = self._aiohttp.CookieJar(unsafe=True)
        self.import_cookies(state.cookies, merge=True)
        self._session = self._aiohttp.ClientSession(
            connector=self._connector,
            cookie_jar=self._cookie_jar,
            trust_env=self.trust_env,
        )
        return self._session

    def _build_headers(self, spec: RequestSpec, state: SessionState) -> dict[str, str]:
        """
        合并默认头、会话级头和请求头。

        Args:
            spec (RequestSpec): 请求规格。
            state (SessionState): 会话状态。

        Returns:
            dict[str, str]: 请求头。
        """

        headers: dict[str, str] = {}
        headers.update(state.default_headers)
        headers.update(state.headers_sticky)
        if state.user_agent and "User-Agent" not in headers:
            headers["User-Agent"] = state.user_agent
        if spec.headers:
            headers.update(spec.headers)
        return headers

    def _build_timeout(self, spec: RequestSpec) -> Any:
        """
        构造请求超时对象。

        Args:
            spec (RequestSpec): 请求规格。

        Returns:
            Any: aiohttp ClientTimeout。
        """

        aiohttp = load_aiohttp()
        if spec.timeout is None:
            return aiohttp.ClientTimeout(
                total=self.limits.total_timeout,
                connect=self.limits.connect_timeout,
                sock_read=self.limits.read_timeout,
            )
        return aiohttp.ClientTimeout(
            total=spec.timeout,
            connect=self.limits.connect_timeout,
            sock_read=self.limits.read_timeout,
        )

    def _build_request_options(self, spec: RequestSpec) -> dict[str, Any]:
        """
        从请求元数据构造 aiohttp 请求选项。

        Args:
            spec (RequestSpec): 请求规格。

        Returns:
            dict[str, Any]: aiohttp 请求选项。
        """

        options: dict[str, Any] = {}
        meta = spec.meta or {}
        if "allow_redirects" in meta:
            options["allow_redirects"] = bool(meta["allow_redirects"])
        if "cookies" in meta:
            options["cookies"] = meta["cookies"]
        if "auth" in meta:
            options["auth"] = meta["auth"]
        if "proxy_headers" in meta:
            options["proxy_headers"] = meta["proxy_headers"]
        if "ssl" in meta:
            options["ssl"] = meta["ssl"]
        elif meta.get("verify") is False:
            options["ssl"] = False
        return options

    async def _read_response_body(self, response: Any) -> tuple[bytes, str | None]:
        """
        读取响应体，超过阈值时落盘。

        Args:
            response (Any): aiohttp 响应对象。

        Returns:
            tuple[bytes, str | None]: 内存响应体和落盘路径。
        """

        chunks: list[bytes] = []
        total = 0
        file = None
        content_path = None
        threshold = self.limits.spool_to_disk_threshold

        try:
            async for chunk in response.content.iter_chunked(64 * 1024):
                total += len(chunk)
                if file is None and total > threshold:
                    directory = self.limits.spool_path()
                    if directory is not None:
                        directory.mkdir(parents=True, exist_ok=True)
                    file = tempfile.NamedTemporaryFile(
                        mode="wb",
                        delete=False,
                        suffix=".body",
                        dir=str(directory) if directory else None,
                    )
                    content_path = file.name
                    for cached in chunks:
                        file.write(cached)
                    chunks.clear()

                if file is not None:
                    file.write(chunk)
                else:
                    chunks.append(chunk)
        finally:
            if file is not None:
                file.close()

        if content_path is not None:
            return b"", content_path
        return b"".join(chunks), None

    def _map_exception(self, exc: Exception, spec: RequestSpec) -> Exception:
        """
        将 aiohttp 异常映射为 SDK 异常。

        Args:
            exc (Exception): 原始异常。
            spec (RequestSpec): 请求规格。

        Returns:
            Exception: SDK 异常。
        """

        aiohttp = self._aiohttp or load_aiohttp()
        message = str(exc)
        lowered_message = message.lower()
        http_proxy_error = getattr(aiohttp, "ClientHttpProxyError", ())
        proxy_connection_error = getattr(aiohttp, "ClientProxyConnectionError", ())
        tls_errors = tuple(
            item
            for item in (
                getattr(aiohttp, "ClientConnectorSSLError", None),
                getattr(aiohttp, "ClientSSLError", None),
                getattr(aiohttp, "ServerFingerprintMismatch", None),
            )
            if item is not None
        )
        auth_markers = (
            "authentication failure",
            "username and password authentication failure",
            "proxy authentication",
            "invalid username or password",
            "login failed",
        )

        if http_proxy_error and isinstance(exc, http_proxy_error):
            if getattr(exc, "status", None) == 407:
                return ProxyAuthError(message, proxy_snapshot=self.proxy_snapshot, request_tag=spec.tag)
            return ProxyConnectionError(message, proxy_snapshot=self.proxy_snapshot, request_tag=spec.tag)
        if any(marker in lowered_message for marker in auth_markers):
            return ProxyAuthError(message, proxy_snapshot=self.proxy_snapshot, request_tag=spec.tag)
        if proxy_connection_error and isinstance(exc, proxy_connection_error):
            return ProxyConnectionError(message, proxy_snapshot=self.proxy_snapshot, request_tag=spec.tag)
        if tls_errors and isinstance(exc, tls_errors):
            return TLSError(message, proxy_snapshot=self.proxy_snapshot, request_tag=spec.tag)
        if isinstance(exc, (aiohttp.ServerTimeoutError, asyncio.TimeoutError, TimeoutError)):
            return ProxyTimeoutError(message, proxy_snapshot=self.proxy_snapshot, request_tag=spec.tag)
        if isinstance(exc, aiohttp.ClientConnectorError):
            return TargetConnectionError(message, proxy_snapshot=self.proxy_snapshot, request_tag=spec.tag)
        if isinstance(exc, aiohttp.ClientConnectionError):
            return TargetConnectionError(message, proxy_snapshot=self.proxy_snapshot, request_tag=spec.tag)
        if isinstance(exc, aiohttp.ClientResponseError):
            return ProtocolError(message, proxy_snapshot=self.proxy_snapshot, request_tag=spec.tag)
        return ProtocolError(message, proxy_snapshot=self.proxy_snapshot, request_tag=spec.tag)


__all__ = ["AiohttpTransport"]


def _parse_cookie_expiry(expires: str, max_age: str) -> float | None:
    """
    解析 Cookie 过期时间。

    Args:
        expires (str): expires 原始字符串。
        max_age (str): max-age 原始字符串。

    Returns:
        float | None: Unix 时间戳，解析失败返回 None。
    """

    if max_age:
        try:
            return time.time() + int(max_age)
        except (TypeError, ValueError, OverflowError):
            return None
    if not expires:
        return None
    try:
        return parsedate_to_datetime(expires).timestamp()
    except (TypeError, ValueError, OverflowError):
        return None
