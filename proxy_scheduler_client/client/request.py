"""
代理请求规格模型。
"""

from __future__ import annotations

import json as json_module
import os
import shlex
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_CURL_PROXY_PROTOCOL_ALIASES = {
    "": "http",
    "http": "http",
    "https": "https",
    "socks5": "socks5",
    "socks5h": "socks5h",
    "socket5": "socks5",
    "socket5h": "socks5h",
}


@dataclass(slots=True)
class RequestSpec:
    """
    描述一次待发送的 HTTP 请求。

    Args:
        method (str): HTTP 方法。
        url (str): 请求 URL。
        headers (dict[str, str] | None): 请求头。
        params (dict[str, Any] | None): 查询参数。
        data (Any): 表单或原始请求体。
        json (Any): JSON 请求体。
        timeout (float | None): 单请求总超时时间。
        tag (str | None): 请求标签。
        meta (dict[str, Any]): 自定义上下文。

    Returns:
        None: 数据对象无返回值。
    """

    method: str
    url: str
    headers: dict[str, str] | None = None
    params: dict[str, Any] | None = None
    data: Any = None
    json: Any = None
    timeout: float | None = None
    tag: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_curl(
        self,
        *,
        pretty: bool = False,
        masked: bool = False,
        shell: str = "auto",
        proxy_url: str | None = None,
        cookies: dict[str, str] | None = None,
        extra_headers: dict[str, str] | None = None,
        insecure: bool = False,
        connect_timeout: float | None = None,
    ) -> str:
        """
        将当前请求规格导出为可执行的 curl 命令。

        Args:
            pretty (bool): 是否输出适合终端阅读的多行命令。
            masked (bool): 是否对敏感信息进行脱敏。
            shell (str): 目标终端类型，支持 auto、bash、powershell 和 cmd。
            proxy_url (str | None): 可选代理地址。
            cookies (dict[str, str] | None): 额外 Cookie 映射。
            extra_headers (dict[str, str] | None): 额外请求头，优先级低于当前请求头。
            insecure (bool): 是否强制输出 `-k`。
            connect_timeout (float | None): 连接超时时间，单位为秒。

        Returns:
            str: curl 命令字符串。
        """

        normalized_shell = _normalize_shell(shell)
        merged_headers = _merge_header_mappings(extra_headers, self.headers)

        meta = dict(self.meta or {})
        final_url = _merge_url_and_params(self.url, self.params)
        final_cookies = _merge_cookie_mappings(cookies, _normalize_cookie_mapping(meta.get("cookies")))
        explicit_cookie = _get_header_value(merged_headers, "Cookie")
        if explicit_cookie is None and final_cookies:
            merged_headers["Cookie"] = _format_cookie_header(final_cookies)

        body_flag, body_value, content_type = _build_body_for_curl(self.data, self.json, masked=masked)
        if content_type and not _has_header(merged_headers, "Content-Type"):
            merged_headers["Content-Type"] = content_type

        command_parts: list[str] = [_curl_command_name(normalized_shell)]
        allow_redirects = bool(meta.get("allow_redirects", True))
        if allow_redirects:
            command_parts.append("-L")
        if insecure or meta.get("verify") is False or meta.get("ssl") is False:
            command_parts.append("-k")
        if connect_timeout is not None:
            command_parts.extend(["--connect-timeout", _quote_curl_arg(str(connect_timeout), normalized_shell)])
        if self.timeout is not None:
            command_parts.extend(["--max-time", _quote_curl_arg(str(self.timeout), normalized_shell)])
        if proxy_url:
            command_parts.extend(_build_proxy_command_parts(proxy_url, masked=masked, shell=normalized_shell))

        auth_value = _extract_auth_value(meta.get("auth"))
        if auth_value:
            command_parts.extend(
                ["-u", _quote_curl_arg(_mask_auth_value(auth_value) if masked else auth_value, normalized_shell)]
            )

        method = str(self.method or "GET").upper()
        if method != "GET" or body_value is not None:
            command_parts.extend(["-X", _quote_curl_arg(method, normalized_shell)])

        for name, value in merged_headers.items():
            header_value = _mask_header_value(name, value) if masked else value
            command_parts.extend(["-H", _quote_curl_arg(f"{name}: {header_value}", normalized_shell)])

        proxy_headers = _normalize_header_items(meta.get("proxy_headers"))
        for name, value in proxy_headers:
            proxy_header_value = _mask_header_value(name, value) if masked else value
            command_parts.extend(
                ["--proxy-header", _quote_curl_arg(f"{name}: {proxy_header_value}", normalized_shell)]
            )

        if body_flag and body_value is not None:
            command_parts.extend([body_flag, _quote_curl_arg(body_value, normalized_shell)])

        rendered_url = _mask_url(final_url) if masked else final_url
        command_parts.append(_quote_curl_arg(rendered_url, normalized_shell))
        return _render_curl_command(command_parts, pretty=pretty, shell=normalized_shell)

    def to_dict(self) -> dict[str, Any]:
        """
        将请求规格转换为可序列化字典。

        Returns:
            dict[str, Any]: 请求规格字典。
        """

        return {
            "method": self.method,
            "url": self.url,
            "headers": self.headers,
            "params": self.params,
            "data": self.data,
            "json": self.json,
            "timeout": self.timeout,
            "tag": self.tag,
            "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RequestSpec":
        """
        从字典恢复请求规格。

        Args:
            data (dict[str, Any]): 请求规格字典。

        Returns:
            RequestSpec: 请求规格对象。
        """

        return cls(
            method=str(data["method"]),
            url=str(data["url"]),
            headers=data.get("headers"),
            params=data.get("params"),
            data=data.get("data"),
            json=data.get("json"),
            timeout=data.get("timeout"),
            tag=data.get("tag"),
            meta=dict(data.get("meta") or {}),
        )


def _merge_url_and_params(url: str, params: dict[str, Any] | None) -> str:
    """
    合并 URL 和查询参数。

    Args:
        url (str): 原始 URL。
        params (dict[str, Any] | None): 查询参数。

    Returns:
        str: 合并后的 URL。
    """

    if not params:
        return url

    parsed = urlsplit(url)
    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    for key, value in params.items():
        if isinstance(value, (list, tuple)):
            for item in value:
                query_items.append((str(key), "" if item is None else str(item)))
        else:
            query_items.append((str(key), "" if value is None else str(value)))
    return urlunsplit(parsed._replace(query=urlencode(query_items, doseq=True)))


def _merge_cookie_mappings(
    base: dict[str, str] | None,
    override: dict[str, str] | None,
) -> dict[str, str]:
    """
    合并两组 Cookie 映射。

    Args:
        base (dict[str, str] | None): 基础 Cookie。
        override (dict[str, str] | None): 覆盖 Cookie。

    Returns:
        dict[str, str]: 合并后的 Cookie。
    """

    result: dict[str, str] = {}
    if base:
        result.update({str(key): str(value) for key, value in base.items()})
    if override:
        result.update({str(key): str(value) for key, value in override.items()})
    return result


def _normalize_cookie_mapping(value: Any) -> dict[str, str] | None:
    """
    规范化 Cookie 输入。

    Args:
        value (Any): 原始 Cookie 输入。

    Returns:
        dict[str, str] | None: 规范化后的 Cookie 映射。
    """

    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): str(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        result: dict[str, str] = {}
        for item in value:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                result[str(item[0])] = str(item[1])
        return result
    return None


def _normalize_header_mapping(value: Any) -> dict[str, str]:
    """
    规范化请求头映射。

    Args:
        value (Any): 原始请求头输入。

    Returns:
        dict[str, str]: 规范化后的请求头映射。
    """

    if value is None:
        return {}
    if isinstance(value, dict):
        return {str(key): str(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        result: dict[str, str] = {}
        for item in value:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                result[str(item[0])] = str(item[1])
        return result
    return {}


def _normalize_header_items(value: Any) -> list[tuple[str, str]]:
    """
    规范化请求头输入为有序键值对列表。

    Args:
        value (Any): 原始请求头输入。

    Returns:
        list[tuple[str, str]]: 有序请求头列表。
    """

    if value is None:
        return []
    if isinstance(value, dict):
        return [(str(key), str(item)) for key, item in value.items()]
    if isinstance(value, (list, tuple)):
        result: list[tuple[str, str]] = []
        for item in value:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                result.append((str(item[0]), str(item[1])))
        return result
    return []


def _merge_header_mappings(*mappings: Any) -> dict[str, str]:
    """
    以大小写不敏感方式合并多组请求头。

    Args:
        *mappings (Any): 多组请求头输入。

    Returns:
        dict[str, str]: 合并后的请求头映射。
    """

    merged: dict[str, tuple[str, str]] = {}
    for mapping in mappings:
        for name, value in _normalize_header_items(mapping):
            merged[name.lower()] = (name, value)
    return {name: value for name, value in merged.values()}


def _build_body_for_curl(
    data: Any,
    json_value: Any,
    *,
    masked: bool,
) -> tuple[str | None, str | None, str | None]:
    """
    将请求体转换为 curl 参数。

    Args:
        data (Any): 表单或原始请求体。
        json_value (Any): JSON 请求体。
        masked (bool): 是否脱敏敏感字段。

    Returns:
        tuple[str | None, str | None, str | None]: curl body 参数名、参数值和内容类型。
    """

    if json_value is not None:
        if isinstance(json_value, str):
            if masked:
                try:
                    payload = _mask_json_like(json_module.loads(json_value))
                    return (
                        "--data-raw",
                        json_module.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                        "application/json",
                    )
                except json_module.JSONDecodeError:
                    return "--data-raw", json_value, "application/json"
            return "--data-raw", json_value, "application/json"
        payload = _mask_json_like(json_value) if masked else json_value
        return (
            "--data-raw",
            json_module.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            "application/json",
        )
    if data is None:
        return None, None, None
    if isinstance(data, (bytes, bytearray)):
        raise ValueError("binary request bodies are not supported for curl export; write to a file first")
    if isinstance(data, dict):
        payload = _mask_json_like(data) if masked else data
        return "--data-raw", urlencode(payload, doseq=True), "application/x-www-form-urlencoded"
    if isinstance(data, (list, tuple)):
        if all(isinstance(item, (list, tuple)) and len(item) == 2 for item in data):
            payload = _mask_json_like(list(data)) if masked else data
            return "--data-raw", urlencode(payload, doseq=True), "application/x-www-form-urlencoded"
    return "--data-raw", str(data), None


def _mask_json_like(value: Any) -> Any:
    """
    递归脱敏 JSON 风格的数据结构。

    Args:
        value (Any): 原始数据。

    Returns:
        Any: 脱敏后的数据。
    """

    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            text_key = str(key)
            if _is_sensitive_key(text_key):
                result[text_key] = "***"
            else:
                result[text_key] = _mask_json_like(item)
        return result
    if isinstance(value, list):
        return [_mask_json_like(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_mask_json_like(item) for item in value)
    return value


def _has_header(headers: dict[str, str], name: str) -> bool:
    """
    判断请求头是否存在指定名称。

    Args:
        headers (dict[str, str]): 请求头映射。
        name (str): 目标请求头名称。

    Returns:
        bool: 存在返回 True。
    """

    target = name.lower()
    return any(str(key).lower() == target for key in headers)


def _get_header_value(headers: dict[str, str], name: str) -> str | None:
    """
    按名称获取请求头值。

    Args:
        headers (dict[str, str]): 请求头映射。
        name (str): 目标请求头名称。

    Returns:
        str | None: 请求头值。
    """

    target = name.lower()
    for key, value in headers.items():
        if str(key).lower() == target:
            return str(value)
    return None


def _format_cookie_header(cookies: dict[str, str]) -> str:
    """
    将 Cookie 映射格式化为请求头字符串。

    Args:
        cookies (dict[str, str]): Cookie 映射。

    Returns:
        str: Cookie 请求头值。
    """

    return "; ".join(f"{key}={value}" for key, value in cookies.items())


def _extract_auth_value(auth: Any) -> str | None:
    """
    从认证对象中提取 user:password 形式的字符串。

    Args:
        auth (Any): 原始认证对象。

    Returns:
        str | None: 认证字符串。
    """

    if auth is None:
        return None
    if isinstance(auth, str):
        return auth
    if isinstance(auth, (list, tuple)) and len(auth) == 2:
        return f"{auth[0]}:{auth[1]}"
    login = getattr(auth, "login", None)
    if login is None:
        login = getattr(auth, "user", None)
    if login is None:
        login = getattr(auth, "username", None)
    password = getattr(auth, "password", None)
    if password is None:
        password = getattr(auth, "passwd", None)
    if password is None:
        password = getattr(auth, "secret", None)
    if login is not None and password is not None:
        return f"{login}:{password}"
    return None


def _mask_auth_value(value: str) -> str:
    """
    脱敏认证字符串中的密码部分。

    Args:
        value (str): 认证字符串。

    Returns:
        str: 脱敏后的认证字符串。
    """

    if ":" not in value:
        return "***"
    user, _ = value.split(":", 1)
    return f"{user}:***"


def _mask_header_value(name: str, value: str) -> str:
    """
    按请求头名称脱敏敏感值。

    Args:
        name (str): 请求头名称。
        value (str): 请求头值。

    Returns:
        str: 脱敏后的请求头值。
    """

    header_name = name.lower()
    if header_name in {"authorization", "proxy-authorization"}:
        if " " in value:
            scheme, _ = value.split(" ", 1)
            return f"{scheme} ***"
        return "***"
    if header_name == "cookie":
        return "***"
    if _is_sensitive_key(header_name):
        return "***"
    return value


def _is_sensitive_key(key: str) -> bool:
    """
    判断字段名是否属于敏感字段。

    Args:
        key (str): 字段名。

    Returns:
        bool: 敏感字段返回 True。
    """

    normalized = "".join(char.lower() if char.isalnum() else "_" for char in str(key))
    tokens = {token for token in normalized.split("_") if token}
    exact_matches = {
        "password",
        "passwd",
        "secret",
        "token",
        "api",
        "apikey",
        "api_key",
        "access",
        "access_token",
        "refresh",
        "refresh_token",
        "auth",
        "auth_token",
        "authorization",
        "bearer",
        "signature",
        "sign",
        "credential",
        "credentials",
        "csrf",
        "csrf_token",
    }
    if normalized in exact_matches:
        return True
    if "api" in tokens and "key" in tokens:
        return True
    if "access" in tokens and "token" in tokens:
        return True
    if "refresh" in tokens and "token" in tokens:
        return True
    if "auth" in tokens and "token" in tokens:
        return True
    if "csrf" in tokens and "token" in tokens:
        return True
    return any(token in exact_matches for token in tokens)


def _mask_url(url: str) -> str:
    """
    脱敏 URL 中的敏感查询参数。

    Args:
        url (str): 原始 URL。

    Returns:
        str: 脱敏后的 URL。
    """

    parsed = urlsplit(url)
    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    if not query_items:
        return url
    masked_query = [
        (key, "***" if _is_sensitive_key(key) else value)
        for key, value in query_items
    ]
    return urlunsplit(parsed._replace(query=urlencode(masked_query, doseq=True)))


def _mask_proxy_url(proxy_url: str) -> str:
    """
    脱敏代理地址中的认证信息。

    Args:
        proxy_url (str): 原始代理地址。

    Returns:
        str: 脱敏代理地址。
    """

    parts = urlsplit(proxy_url)
    if "@" not in parts.netloc:
        return proxy_url

    userinfo, hostinfo = parts.netloc.rsplit("@", 1)
    username = "***" if userinfo else ""
    password = ":***" if ":" in userinfo else ""
    netloc = f"{username}{password}@{hostinfo}"
    return parts._replace(netloc=netloc).geturl()


def _normalize_shell(shell: str) -> str:
    """
    标准化 curl 命令的目标终端类型。

    Args:
        shell (str): 原始终端类型。

    Returns:
        str: 标准化后的终端类型。

    Raises:
        ValueError: 终端类型不支持时抛出。
    """

    normalized = str(shell or "auto").strip().lower()
    if normalized == "auto":
        return "cmd" if os.name == "nt" else "bash"
    if normalized not in {"bash", "powershell", "cmd"}:
        raise ValueError("shell must be 'auto', 'bash', 'powershell' or 'cmd'")
    return normalized


def _quote_curl_arg(value: str, shell: str) -> str:
    """
    将参数转换为适合目标终端直接执行的字符串。

    Args:
        value (str): 原始参数值。
        shell (str): 目标终端类型。

    Returns:
        str: 已转义的参数值。
    """

    text = str(value)
    if shell == "bash":
        return shlex.quote(text)
    if shell == "cmd":
        return _quote_windows_arg(text, escape_percent=True)
    return _quote_windows_arg(text, escape_percent=False)


def _quote_windows_arg(value: str, *, escape_percent: bool) -> str:
    """
    将参数转换为适合 Windows 终端直接执行的双引号字符串。

    Args:
        value (str): 原始参数值。
        escape_percent (bool): 是否对百分号做额外转义。

    Returns:
        str: 已转义的参数值。
    """

    text = str(value)
    if escape_percent:
        text = text.replace("%", "%%")
    pieces: list[str] = ['"']
    backslashes = 0

    for char in text:
        if char == "\\":
            backslashes += 1
            continue
        if char == '"':
            pieces.append("\\" * (backslashes * 2 + 1))
            pieces.append('"')
            backslashes = 0
            continue
        if backslashes:
            pieces.append("\\" * backslashes)
            backslashes = 0
        pieces.append(char)

    if backslashes:
        pieces.append("\\" * (backslashes * 2))
    pieces.append('"')
    return "".join(pieces)


def _render_curl_command(parts: list[str], *, pretty: bool, shell: str) -> str:
    """
    渲染 curl 命令字符串。

    Args:
        parts (list[str]): 命令片段列表。
        pretty (bool): 是否输出多行命令。
        shell (str): 目标终端类型。

    Returns:
        str: 渲染后的 curl 命令。
    """

    if shell == "powershell" and parts and parts[0] in {"curl", "curl.exe"}:
        parts = [parts[0], "--%"] + parts[1:]
    if not pretty or shell in {"cmd", "powershell"}:
        return " ".join(parts)
    separator = " \\\n  "
    return separator.join(parts)


def _curl_command_name(shell: str) -> str:
    """
    根据目标终端返回合适的 curl 可执行文件名。

    Args:
        shell (str): 目标终端类型。

    Returns:
        str: curl 命令名。
    """

    if shell in {"cmd", "powershell"}:
        return "curl.exe"
    return "curl"


def _build_proxy_command_parts(proxy_url: str, *, masked: bool, shell: str) -> list[str]:
    """
    根据代理协议构造 curl 代理参数。

    Args:
        proxy_url (str): 原始代理地址。
        masked (bool): 是否对敏感信息脱敏。
        shell (str): 目标终端类型。

    Returns:
        list[str]: curl 命令片段列表。
    """

    original_proxy_url = str(proxy_url).strip()
    proxy_url_for_parse = original_proxy_url if "://" in original_proxy_url else f"http://{original_proxy_url}"
    parsed = urlsplit(proxy_url_for_parse)
    raw_scheme = parsed.scheme.lower() if "://" in original_proxy_url else ""
    try:
        scheme = _CURL_PROXY_PROTOCOL_ALIASES[raw_scheme]
    except KeyError as exc:
        supported = ", ".join(sorted(key for key in _CURL_PROXY_PROTOCOL_ALIASES if key))
        raise ValueError(
            f"unsupported proxy protocol for curl export: {raw_scheme!r}. Supported: {supported}"
        ) from exc

    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = parsed.port
    host_port = f"{host}:{port}" if port is not None else host

    auth_parts: list[str] = []
    if parsed.username or parsed.password:
        username = parsed.username or ""
        password = parsed.password or ""
        auth_value = f"{username}:{password}"
        auth_parts.extend(
            ["-U", _quote_curl_arg(_mask_auth_value(auth_value) if masked else auth_value, shell)]
        )

    if not host:
        raise ValueError("proxy_url must include a hostname for curl export")

    if scheme == "socks5h":
        return ["--socks5-hostname", _quote_curl_arg(host_port, shell), *auth_parts]
    if scheme == "socks5":
        return ["--socks5", _quote_curl_arg(host_port, shell), *auth_parts]
    if scheme == "http":
        return ["-x", _quote_curl_arg(f"http://{host_port}", shell), *auth_parts]
    if scheme == "https":
        return ["-x", _quote_curl_arg(f"https://{host_port}", shell), *auth_parts]

    raise ValueError(
        f"unsupported normalized proxy protocol for curl export: {scheme!r}"
    )
