"""
IPWEB 动态代理地址生成核心模块。

本模块只负责根据账号、网关、地区、协议和会话参数生成代理地址，
不发起网络请求，不维护代理池，也不判断代理是否可用。
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Iterator
from urllib.parse import quote, urlsplit

from .geo import load_geo_index


DEFAULT_PORT = 7778
MIN_DURATION_MINUTES = 1
MAX_DURATION_MINUTES = 1440
MAX_GENERATE_COUNT = 10_000_000
IN_MEMORY_LIST_GENERATE_THRESHOLD = 100_000
_SESSION_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_USER_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_PROTOCOL_ALIASES = {
    "http": "http",
    "https": "https",
    "socks5": "socks5",
    "socks5h": "socks5h",
    "socket5": "socks5",
    "socket5h": "socks5h",
}


class Gateway:
    """
    IPWEB 官方网关别名规范化工具。
    """

    _ALIASES = {
        "americas": "gate1.ipweb.cc:7778",
        "america": "gate1.ipweb.cc:7778",
        "us": "gate1.ipweb.cc:7778",
        "apac": "gate2.ipweb.cc:7778",
        "asia": "gate2.ipweb.cc:7778",
        "emea": "gate3.ipweb.cc:7778",
        "europe": "gate3.ipweb.cc:7778",
        "global": "gate1.ipweb.cc:7778",
    }
    _OFFICIAL_GATEWAYS = {
        "gate1.ipweb.cc:7778": "gate1.ipweb.cc:7778",
        "gate2.ipweb.cc:7778": "gate2.ipweb.cc:7778",
        "gate3.ipweb.cc:7778": "gate3.ipweb.cc:7778",
    }

    @classmethod
    def normalize(cls, gateway: str) -> str:
        """
        将官方网关别名转换为 host:port 格式。

        Args:
            gateway (str): 官方网关别名或官方网关地址。

        Returns:
            str: 标准化后的网关地址。

        Raises:
            ValueError: 网关内容为空或不属于官方支持范围时抛出。
        """

        value = str(gateway or "apac").strip()
        if not value:
            raise ValueError("gateway must not be empty")

        key = value.lower()
        if key in cls._ALIASES:
            return cls._ALIASES[key]

        if "://" in value:
            parsed = urlsplit(value)
            if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
                raise ValueError("gateway must not contain path, query or fragment")
            value = parsed.netloc

        candidate = value.lower()
        if ":" not in candidate:
            candidate = f"{candidate}:{DEFAULT_PORT}"
        if candidate in cls._OFFICIAL_GATEWAYS:
            return cls._OFFICIAL_GATEWAYS[candidate]

        supported = ", ".join(sorted(cls._ALIASES))
        raise ValueError(f"unsupported gateway: {gateway!r}. Supported aliases: {supported}")


@dataclass(frozen=True)
class PreparedProxy:
    """
    动态代理生成后的标准返回对象。

    Args:
        proxy_url (str): 当前主协议对应的完整代理地址。
        proxies (dict[str, str]): 多协议代理地址映射。
        username (str): 最终拼接后的代理认证用户名。
        gateway (str): 当前使用的代理网关地址，格式为 host:port。
        host (str): 当前代理网关主机。
        port (int): 当前代理网关端口。
        user (str): 当前代理认证用户名，等同于 username。
        password (str): 当前代理认证密码。
        protocol (str): 当前主代理地址使用的协议。
        session_id (str): 当前代理会话标识。
        country_code (str): 当前代理国家代码。
        state_code (str): 当前代理州代码。
        city_code (str): 当前代理城市代码。
        duration_minutes (int): 当前代理会话时长，单位为分钟。

    Returns:
        None: 数据对象无返回值。
    """

    proxy_url: str
    proxies: dict[str, str]
    username: str
    gateway: str
    host: str = ""
    port: int = DEFAULT_PORT
    user: str = ""
    password: str = ""
    protocol: str = "http"
    session_id: str = ""
    country_code: str = "000"
    state_code: str = ""
    city_code: str = ""
    duration_minutes: int = 5

    def __repr__(self) -> str:
        """
        返回脱敏后的对象展示内容，避免日志中泄露代理账号和密码。

        Returns:
            str: 脱敏后的对象字符串。
        """

        return (
            "PreparedProxy("
            f"proxy_url={self.safe_proxy_url!r}, "
            f"username={self.masked_user!r}, "
            f"gateway={self.gateway!r}, "
            f"host={self.host!r}, "
            f"port={self.port!r}, "
            f"protocol={self.protocol!r}, "
            f"session_id={self.session_id!r}, "
            f"country_code={self.country_code!r}, "
            f"state_code={self.state_code!r}, "
            f"city_code={self.city_code!r}, "
            f"duration_minutes={self.duration_minutes!r}"
            ")"
        )

    @property
    def http_url(self) -> str:
        """
        返回 HTTP 代理地址。

        Returns:
            str: HTTP 代理地址。
        """

        return self.proxies["http"]

    @property
    def https_url(self) -> str:
        """
        返回 HTTPS 目标站可用的 HTTP CONNECT 代理地址。

        Returns:
            str: HTTPS 目标站使用的代理地址。
        """

        return self.proxies["https"]

    @property
    def socks5_url(self) -> str:
        """
        返回 SOCKS5 代理地址。

        Returns:
            str: SOCKS5 代理地址。
        """

        return self.proxies["socks5"]

    @property
    def socks5h_url(self) -> str:
        """
        返回 SOCKS5H 代理地址。

        Returns:
            str: SOCKS5H 代理地址。
        """

        return self.proxies["socks5h"]

    @property
    def masked_password(self) -> str:
        """
        返回脱敏后的代理密码。

        Returns:
            str: 脱敏密码。
        """

        return "***" if self.password else ""

    @property
    def masked_user(self) -> str:
        """
        返回脱敏后的代理用户名。

        Returns:
            str: 脱敏用户名。
        """

        return "***" if self.user or self.username else ""

    @property
    def safe_proxy_url(self) -> str:
        """
        返回脱敏后的主代理地址。

        Returns:
            str: 脱敏代理地址。
        """

        return self._mask_proxy_url(self.proxy_url)

    @property
    def safe_proxies(self) -> dict[str, str]:
        """
        返回脱敏后的多协议代理地址映射。

        Returns:
            dict[str, str]: 脱敏代理地址映射。
        """

        return {
            protocol: self._mask_proxy_url(proxy_url)
            for protocol, proxy_url in self.proxies.items()
        }

    def url_for(self, protocol: str = "http") -> str:
        """
        按协议返回代理地址。

        Args:
            protocol (str): 代理协议，支持 http、https、socks5、socks5h、socket5、socket5h。

        Returns:
            str: 指定协议的代理地址。

        Raises:
            ValueError: 代理协议不支持时抛出。
        """

        normalized = DynamicProxyClient.normalize_protocol(protocol)
        return self.proxies[normalized]

    def to_dict(self, *, masked: bool = True) -> dict[str, object]:
        """
        将代理对象转换为字典。

        Args:
            masked (bool): 是否对密码和代理地址脱敏，默认脱敏。

        Returns:
            dict[str, object]: 代理对象字典。
        """

        return {
            "proxy_url": self.safe_proxy_url if masked else self.proxy_url,
            "proxies": self.safe_proxies if masked else dict(self.proxies),
            "username": self.masked_user if masked else self.username,
            "gateway": self.gateway,
            "host": self.host,
            "port": self.port,
            "user": self.masked_user if masked else self.user,
            "password": self.masked_password if masked else self.password,
            "protocol": self.protocol,
            "session_id": self.session_id,
            "country_code": self.country_code,
            "state_code": self.state_code,
            "city_code": self.city_code,
            "duration_minutes": self.duration_minutes,
        }

    def to_json(self, *, masked: bool = True) -> str:
        """
        将代理对象转换为 JSON 字符串。

        Args:
            masked (bool): 是否对密码和代理地址脱敏，默认脱敏。

        Returns:
            str: JSON 格式的代理对象。
        """

        return json.dumps(self.to_dict(masked=masked), ensure_ascii=False)

    def to_env(self, *, masked: bool = False) -> dict[str, str]:
        """
        返回常见环境变量形式的代理配置。

        Args:
            masked (bool): 是否对环境变量中的代理地址脱敏，默认不脱敏以便直接使用。

        Returns:
            dict[str, str]: 代理环境变量映射。
        """

        proxy_url = self.safe_proxy_url if masked else self.proxy_url
        return {
            "HTTP_PROXY": proxy_url,
            "HTTPS_PROXY": proxy_url,
            "ALL_PROXY": proxy_url,
        }

    def explain(self, *, masked: bool = True) -> dict[str, object]:
        """
        返回代理生成参数和输出结果说明。

        Args:
            masked (bool): 是否对敏感字段脱敏，默认脱敏。

        Returns:
            dict[str, object]: 代理生成说明。
        """

        return {
            "gateway": self.gateway,
            "host": self.host,
            "port": self.port,
            "protocol": self.protocol,
            "country_code": self.country_code,
            "state_code": self.state_code,
            "city_code": self.city_code,
            "duration_minutes": self.duration_minutes,
            "session_id": self.session_id,
            "proxy_url": self.safe_proxy_url if masked else self.proxy_url,
            "user": self.masked_user if masked else self.user,
            "password": self.masked_password if masked else self.password,
        }

    def session_state_hint(self) -> str:
        """
        返回客户端请求层可用于会话状态排错的轻量标识。

        Returns:
            str: 会话状态提示字符串。
        """

        return f"ipweb:{self.session_id}:{self.country_code}:{self.protocol}"

    @staticmethod
    def _mask_proxy_url(proxy_url: str) -> str:
        """
        对代理地址中的密码进行脱敏。

        Args:
            proxy_url (str): 原始代理地址。

        Returns:
            str: 脱敏后的代理地址。
        """

        parts = urlsplit(proxy_url)
        if "@" not in parts.netloc:
            return proxy_url

        userinfo, hostinfo = parts.netloc.rsplit("@", 1)
        username = "***" if userinfo else ""
        password = ":***" if ":" in userinfo else ""
        netloc = f"{username}{password}@{hostinfo}"
        return parts._replace(netloc=netloc).geturl()


@dataclass(frozen=True)
class _NormalizedProxyOptions:
    """
    内部使用的标准化代理生成参数。
    """

    country_code: str
    state_code: str
    city_code: str
    duration_minutes: int
    protocol: str


def generate_session_id() -> str:
    """
    生成 32 位小写十六进制会话标识。

    Returns:
        str: 32 位十六进制字符串。
    """

    return uuid.uuid4().hex


class DynamicProxyClient:
    """
    IPWEB 动态代理地址构建器。
    """

    @staticmethod
    def normalize_protocol(protocol: str = "http") -> str:
        """
        标准化代理协议名称。

        Args:
            protocol (str): 原始协议名称。

        Returns:
            str: 标准化后的协议名称。

        Raises:
            ValueError: 协议不支持时抛出。
        """

        key = str(protocol or "http").strip().lower()
        try:
            return _PROTOCOL_ALIASES[key]
        except KeyError as exc:
            supported = ", ".join(sorted(_PROTOCOL_ALIASES))
            raise ValueError(
                f"unsupported proxy protocol: {protocol!r}. Supported: {supported}"
            ) from exc

    def __init__(self, *, user_id: str, password: str, gateway: str = "apac") -> None:
        """
        初始化 IPWEB 动态代理地址构建器。

        Args:
            user_id (str): IPWEB 代理账号用户标识。
            password (str): IPWEB 代理账号密码。
            gateway (str): IPWEB 官方网关别名或官方网关地址。

        Raises:
            ValueError: 用户标识、密码或网关不合法时抛出。
        """

        self.user_id = self._normalize_user_id(user_id)
        self.password = self._require_non_empty("password", password)
        self.gateway = Gateway.normalize(gateway)
        parsed_gateway = self._parse_gateway(self.gateway)
        self.host = parsed_gateway.hostname or ""
        self.port = parsed_gateway.port or DEFAULT_PORT
        self._encoded_password = quote(self.password, safe="")

    def build_proxy(
        self,
        *,
        country_code: str = "000",
        duration_minutes: int = 5,
        session_id: str | None = None,
        state_code: str = "",
        city_code: str = "",
        protocol: str = "http",
        validate: bool = True,
    ) -> PreparedProxy:
        """
        构建单条动态代理地址。

        Args:
            country_code (str): 国家代码，000 表示不限国家。
            duration_minutes (int): 会话时长，单位为分钟。
            session_id (str | None): 自定义会话标识。
            state_code (str): 州代码。
            city_code (str): 城市代码。
            protocol (str): 主代理协议。
            validate (bool): 是否校验地区和时长参数。

        Returns:
            PreparedProxy: 动态代理对象。

        Raises:
            ValueError: 参数不合法时抛出。
        """

        sid = self.normalize_session_id(session_id or generate_session_id())
        options = self._normalize_proxy_options(
            country_code=country_code,
            duration_minutes=duration_minutes,
            state_code=state_code,
            city_code=city_code,
            protocol=protocol,
            validate=validate,
        )
        proxies, username = self._build_proxy_urls(
            sid=sid,
            country_code=options.country_code,
            state_code=options.state_code,
            city_code=options.city_code,
            duration_minutes=options.duration_minutes,
        )
        return self._create_prepared_proxy(
            proxies=proxies,
            username=username,
            selected_protocol=options.protocol,
            sid=sid,
            options=options,
        )

    def build_proxy_many(
        self,
        count: int,
        *,
        country_code: str = "000",
        duration_minutes: int = 5,
        state_code: str = "",
        city_code: str = "",
        protocol: str = "http",
        validate: bool = True,
    ) -> list[PreparedProxy]:
        """
        批量构建动态代理地址。

        Args:
            count (int): 生成数量。
            country_code (str): 国家代码，000 表示不限国家。
            duration_minutes (int): 会话时长，单位为分钟。
            state_code (str): 州代码。
            city_code (str): 城市代码。
            protocol (str): 主代理协议。
            validate (bool): 是否校验地区和时长参数。

        Returns:
            list[PreparedProxy]: 动态代理对象列表。

        Raises:
            ValueError: 参数不合法时抛出。
        """

        count = self._normalize_count(count)
        if count == 0:
            return []

        return list(
            self.iter_build_proxy(
                count,
                country_code=country_code,
                duration_minutes=duration_minutes,
                state_code=state_code,
                city_code=city_code,
                protocol=protocol,
                validate=validate,
            )
        )

    def iter_build_proxy(
        self,
        count: int,
        *,
        country_code: str = "000",
        duration_minutes: int = 5,
        state_code: str = "",
        city_code: str = "",
        protocol: str = "http",
        validate: bool = True,
    ) -> Iterator[PreparedProxy]:
        """
        按需迭代生成动态代理地址，适合大批量场景。

        Args:
            count (int): 生成数量。
            country_code (str): 国家代码，000 表示不限国家。
            duration_minutes (int): 会话时长，单位为分钟。
            state_code (str): 州代码。
            city_code (str): 城市代码。
            protocol (str): 主代理协议。
            validate (bool): 是否校验地区和时长参数。

        Yields:
            PreparedProxy: 动态代理对象。

        Raises:
            ValueError: 参数不合法时抛出。
        """

        count = self._normalize_count(count)
        if count == 0:
            return

        options = self._normalize_proxy_options(
            country_code=country_code,
            duration_minutes=duration_minutes,
            state_code=state_code,
            city_code=city_code,
            protocol=protocol,
            validate=validate,
        )
        selected_protocol = options.protocol
        build_urls = self._build_proxy_urls
        yielded_count = 0
        session_id_stream = self._iter_unique_session_ids(count)

        while yielded_count < count:
            sid = next(session_id_stream)
            proxies, username = build_urls(
                sid=sid,
                country_code=options.country_code,
                state_code=options.state_code,
                city_code=options.city_code,
                duration_minutes=options.duration_minutes,
            )
            yielded_count += 1
            yield self._create_prepared_proxy(
                proxies=proxies,
                username=username,
                selected_protocol=selected_protocol,
                sid=sid,
                options=options,
            )

    @staticmethod
    def normalize_country_code(country_code: str = "000") -> str:
        """
        标准化国家代码。

        Args:
            country_code (str): 原始国家代码。

        Returns:
            str: 标准化后的国家代码。
        """

        return str(country_code or "000").strip().upper()

    @staticmethod
    def normalize_location_code(code: str | int | None) -> str:
        """
        标准化州代码或城市代码。

        Args:
            code (str | int | None): 原始地区代码。

        Returns:
            str: 标准化后的地区代码。
        """

        if code is None:
            return ""
        return str(code).strip()

    @staticmethod
    def normalize_session_id(session_id: str) -> str:
        """
        校验并标准化会话标识。

        Args:
            session_id (str): 原始会话标识。

        Returns:
            str: 标准化后的 32 位小写十六进制字符串。

        Raises:
            ValueError: 会话标识不是 32 位十六进制字符串时抛出。
        """

        value = str(session_id or "").strip().lower()
        if not _SESSION_ID_RE.fullmatch(value):
            raise ValueError("session_id must be a 32-character hexadecimal string")
        return value

    def validate_proxy_params(
        self,
        *,
        country_code: str,
        duration_minutes: int,
        session_id: str,
        state_code: str = "",
        city_code: str = "",
    ) -> None:
        """
        校验完整代理生成参数。

        Args:
            country_code (str): 国家代码。
            duration_minutes (int): 会话时长，单位为分钟。
            session_id (str): 会话标识。
            state_code (str): 州代码。
            city_code (str): 城市代码。

        Returns:
            None: 校验通过时无返回值。

        Raises:
            ValueError: 任一参数不合法时抛出。
        """

        self.normalize_session_id(session_id)
        self.validate_location_params(
            country_code=country_code,
            duration_minutes=duration_minutes,
            state_code=state_code,
            city_code=city_code,
        )

    def validate_location_params(
        self,
        *,
        country_code: str,
        duration_minutes: int,
        state_code: str = "",
        city_code: str = "",
    ) -> None:
        """
        校验国家、州、城市和会话时长参数。

        Args:
            country_code (str): 国家代码。
            duration_minutes (int): 会话时长，单位为分钟。
            state_code (str): 州代码。
            city_code (str): 城市代码。

        Returns:
            None: 校验通过时无返回值。

        Raises:
            ValueError: 参数不合法时抛出。
        """

        duration = self._normalize_duration(duration_minutes)
        if duration < MIN_DURATION_MINUTES or duration > MAX_DURATION_MINUTES:
            raise ValueError(
                "duration_minutes must be between "
                f"{MIN_DURATION_MINUTES} and {MAX_DURATION_MINUTES}"
            )

        country_code = self.normalize_country_code(country_code)
        state_code = self.normalize_location_code(state_code)
        city_code = self.normalize_location_code(city_code)

        if country_code == "000":
            if state_code:
                raise ValueError("state_code requires a specific country_code, not '000'")
            if city_code:
                raise ValueError("city_code requires a specific country_code, not '000'")
            return

        if not re.fullmatch(r"[A-Z]{2}", country_code):
            raise ValueError("country_code must be '000' or a 2-letter ISO country code")

        geo = load_geo_index()
        if country_code not in geo.countries:
            raise ValueError(f"unsupported country_code: {country_code}")

        if state_code and state_code not in geo.states_by_country.get(country_code, frozenset()):
            raise ValueError(
                f"invalid state_code {state_code!r} for country_code {country_code!r}"
            )

        if city_code:
            country_cities = geo.cities_by_country.get(country_code, frozenset())
            if city_code not in country_cities:
                raise ValueError(
                    f"invalid city_code {city_code!r} for country_code {country_code!r}"
                )
            if state_code:
                expected_state = geo.city_to_state_by_country[country_code].get(city_code)
                if expected_state != state_code:
                    raise ValueError(
                        f"city_code {city_code!r} does not belong to state_code {state_code!r}"
                    )

    @staticmethod
    def _normalize_duration(duration_minutes: int) -> int:
        """
        标准化会话时长为整数。

        Args:
            duration_minutes (int): 原始会话时长。

        Returns:
            int: 整数会话时长。

        Raises:
            ValueError: 会话时长不是整数时抛出。
        """

        if isinstance(duration_minutes, bool):
            raise ValueError("duration_minutes must be an integer")
        if isinstance(duration_minutes, int):
            return duration_minutes

        value = str(duration_minutes).strip()
        if not value.isdigit():
            raise ValueError("duration_minutes must be an integer")
        return int(value)

    @staticmethod
    def _normalize_count(count: int) -> int:
        """
        标准化并校验批量生成数量。

        Args:
            count (int): 原始生成数量。

        Returns:
            int: 标准化后的生成数量。

        Raises:
            ValueError: 生成数量不合法时抛出。
        """

        if isinstance(count, bool):
            raise ValueError("count must be an integer")
        if isinstance(count, int):
            value = count
        else:
            text = str(count).strip()
            if not text.isdigit():
                raise ValueError("count must be an integer")
            value = int(text)

        if value < 0:
            raise ValueError("count must be >= 0")
        if value > MAX_GENERATE_COUNT:
            raise ValueError(f"count must be <= {MAX_GENERATE_COUNT}")
        return value

    def should_stream_generate(self, count: int) -> bool:
        """
        判断当前生成数量是否应自动切换为流式返回。

        Args:
            count (int): 标准化后的生成数量。

        Returns:
            bool: 需要流式返回时返回 True。
        """

        return count > IN_MEMORY_LIST_GENERATE_THRESHOLD

    def _iter_unique_session_ids(self, count: int) -> Iterator[str]:
        """
        为单次批量生成按顺序产出全局唯一的 32 位十六进制会话标识。

        Args:
            count (int): 本次需要生成的数量。

        Yields:
            str: 32 位十六进制会话标识。
        """

        call_prefix = uuid.uuid4().hex[:16]
        for index in range(count):
            yield f"{call_prefix}{index:016x}"

    @staticmethod
    def _require_non_empty(name: str, value: str) -> str:
        """
        校验字符串参数不能为空。

        Args:
            name (str): 参数名称。
            value (str): 参数值。

        Returns:
            str: 去除首尾空白后的参数值。

        Raises:
            ValueError: 参数为空时抛出。
        """

        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{name} must not be empty")
        return text

    @classmethod
    def _normalize_user_id(cls, user_id: str) -> str:
        """
        标准化并校验 IPWEB 用户标识。

        Args:
            user_id (str): 原始用户标识。

        Returns:
            str: 标准化后的用户标识。

        Raises:
            ValueError: 用户标识为空或格式不合法时抛出。
        """

        value = cls._require_non_empty("user_id", user_id)
        if not _USER_ID_RE.fullmatch(value):
            raise ValueError("user_id only supports letters, numbers, underscore, dot and hyphen")
        return value

    @staticmethod
    def _parse_gateway(gateway: str):
        """
        解析并校验网关地址。

        Args:
            gateway (str): 标准化后的网关地址。

        Returns:
            SplitResult: 解析后的网关结构。

        Raises:
            ValueError: 网关主机或端口不合法时抛出。
        """

        try:
            parsed_gateway = urlsplit(f"//{gateway}")
            port = parsed_gateway.port
        except ValueError as exc:
            raise ValueError(f"invalid proxy gateway: {gateway!r}") from exc

        if not parsed_gateway.hostname or port is None:
            raise ValueError(f"invalid proxy gateway: {gateway!r}")
        if port <= 0 or port > 65535:
            raise ValueError(f"invalid proxy gateway port: {port!r}")
        return parsed_gateway

    def _normalize_proxy_options(
        self,
        *,
        country_code: str,
        duration_minutes: int,
        state_code: str,
        city_code: str,
        protocol: str,
        validate: bool,
    ) -> _NormalizedProxyOptions:
        """
        标准化代理生成参数。

        Args:
            country_code (str): 国家代码。
            duration_minutes (int): 会话时长。
            state_code (str): 州代码。
            city_code (str): 城市代码。
            protocol (str): 主代理协议。
            validate (bool): 是否执行完整校验。

        Returns:
            _NormalizedProxyOptions: 标准化后的参数对象。
        """

        options = _NormalizedProxyOptions(
            country_code=self.normalize_country_code(country_code),
            state_code=self.normalize_location_code(state_code),
            city_code=self.normalize_location_code(city_code),
            duration_minutes=self._normalize_duration(duration_minutes),
            protocol=self.normalize_protocol(protocol),
        )
        if validate:
            self.validate_location_params(
                country_code=options.country_code,
                duration_minutes=options.duration_minutes,
                state_code=options.state_code,
                city_code=options.city_code,
            )
        return options

    def _build_proxy_urls(
        self,
        *,
        sid: str,
        country_code: str,
        state_code: str,
        city_code: str,
        duration_minutes: int,
    ) -> tuple[dict[str, str], str]:
        """
        拼接多协议代理地址。

        Args:
            sid (str): 会话标识。
            country_code (str): 国家代码。
            state_code (str): 州代码。
            city_code (str): 城市代码。
            duration_minutes (int): 会话时长。

        Returns:
            tuple[dict[str, str], str]: 多协议代理地址映射和代理用户名。
        """

        username = (
            f"{self.user_id}_{country_code}_{state_code}_{city_code}_"
            f"{duration_minutes}_{sid}"
        )
        encoded_user = quote(username, safe="")
        suffix = f"{encoded_user}:{self._encoded_password}@{self.gateway}"
        http_url = f"http://{suffix}"
        return ({
            "http": http_url,
            "https": http_url,
            "socks5": f"socks5://{suffix}",
            "socks5h": f"socks5h://{suffix}",
        }, username)

    def _create_prepared_proxy(
        self,
        *,
        proxies: dict[str, str],
        username: str,
        selected_protocol: str,
        sid: str,
        options: _NormalizedProxyOptions,
    ) -> PreparedProxy:
        """
        创建标准代理返回对象。

        Args:
            proxies (dict[str, str]): 多协议代理地址映射。
            username (str): 代理认证用户名。
            selected_protocol (str): 当前主协议。
            sid (str): 会话标识。
            options (_NormalizedProxyOptions): 标准化生成参数。

        Returns:
            PreparedProxy: 标准代理返回对象。
        """

        return PreparedProxy(
            proxy_url=proxies[selected_protocol],
            proxies=proxies,
            username=username,
            gateway=self.gateway,
            host=self.host,
            port=self.port,
            user=username,
            password=self.password,
            protocol=selected_protocol,
            session_id=sid,
            country_code=options.country_code,
            state_code=options.state_code,
            city_code=options.city_code,
            duration_minutes=options.duration_minutes,
        )
