"""
Small IPWeb tunnel adapter used when the external ipweb_proxy_sdk package
is not installed.

IPWeb's documented self-defined account format is:
    user_id_country_state_city_duration_sid

Example without state/city restrictions:
    B_36424_US___5_Ab000001
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from urllib.parse import quote, urlsplit
from .geo import load_geo_index


DEFAULT_PORT = 7778
_SESSION_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_PROTOCOL_ALIASES = {
    "http": "http",
    "https": "https",
    "socks5": "socks5",
    "socks5h": "socks5h",
    "socket5": "socks5",
    "socket5h": "socks5h",
}
class Gateway:
    """Normalize logical gateway names to IPWeb tunnel hosts."""

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

    @classmethod
    def normalize(cls, gateway: str) -> str:
        value = (gateway or "apac").strip()
        key = value.lower()
        if key in cls._ALIASES:
            return cls._ALIASES[key]
        if "://" in value:
            value = value.split("://", 1)[1]
        return value if ":" in value else f"{value}:{DEFAULT_PORT}"


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
        返回 HTTPS 代理地址。

        Returns:
            str: HTTPS 代理地址。
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

    def url_for(self, protocol: str = "http") -> str:
        """
        按协议返回代理地址。

        Args:
            protocol (str): 代理协议，支持 http、https、socks5、socks5h。

        Returns:
            str: 指定协议的代理地址。
        """

        normalized = DynamicProxyClient.normalize_protocol(protocol)
        return self.proxies[normalized]

@dataclass(frozen=True)
class _NormalizedProxyOptions:
    country_code: str
    state_code: str
    city_code: str
    duration_minutes: int
    protocol: str


def generate_session_id() -> str:
    """Return a 32-character lowercase hexadecimal SID."""

    return uuid.uuid4().hex


class DynamicProxyClient:
    """Build IPWeb HTTP/S proxy URLs from account credentials."""

    @staticmethod
    def normalize_protocol(protocol: str = "http") -> str:
        key = (protocol or "http").strip().lower()
        try:
            return _PROTOCOL_ALIASES[key]
        except KeyError as exc:
            supported = ", ".join(sorted(_PROTOCOL_ALIASES))
            raise ValueError(f"unsupported proxy protocol: {protocol!r}. Supported: {supported}") from exc

    def __init__(self, *, user_id: str, password: str, gateway: str = "apac") -> None:
        self.user_id = self._require_non_empty("user_id", user_id)
        self.password = self._require_non_empty("password", password)
        self.gateway = Gateway.normalize(gateway)
        parsed_gateway = urlsplit(f"//{self.gateway}")
        if not parsed_gateway.hostname or parsed_gateway.port is None:
            raise ValueError(f"invalid proxy gateway: {self.gateway!r}")
        self.host = parsed_gateway.hostname
        self.port = parsed_gateway.port
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
        return PreparedProxy(
            proxy_url=proxies[options.protocol],
            proxies=proxies,
            username=username,
            gateway=self.gateway,
            host=self.host,
            port=self.port,
            user=username,
            password=self.password,
            protocol=options.protocol,
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
        if count < 0:
            raise ValueError("count must be >= 0")
        if count == 0:
            return []

        options = self._normalize_proxy_options(
            country_code=country_code,
            duration_minutes=duration_minutes,
            state_code=state_code,
            city_code=city_code,
            protocol=protocol,
            validate=validate,
        )

        result: list[PreparedProxy] = []
        append = result.append
        gateway = self.gateway
        selected_protocol = options.protocol
        build_urls = self._build_proxy_urls
        create_sid = generate_session_id

        for _ in range(count):
            sid = create_sid()
            proxies, username = build_urls(
                sid=sid,
                country_code=options.country_code,
                state_code=options.state_code,
                city_code=options.city_code,
                duration_minutes=options.duration_minutes,
            )
            append(PreparedProxy(
                proxy_url=proxies[selected_protocol],
                proxies=proxies,
                username=username,
                gateway=gateway,
                host=self.host,
                port=self.port,
                user=username,
                password=self.password,
                protocol=selected_protocol,
            ))

        return result

    @staticmethod
    def normalize_country_code(country_code: str = "000") -> str:
        return str(country_code or "000").strip().upper()

    @staticmethod
    def normalize_location_code(code: str | int | None) -> str:
        if code is None:
            return ""
        return str(code).strip()

    @staticmethod
    def normalize_session_id(session_id: str) -> str:
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
        duration = self._normalize_duration(duration_minutes)
        if duration <= 0:
            raise ValueError("duration_minutes must be > 0")

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
        if isinstance(duration_minutes, bool):
            raise ValueError("duration_minutes must be an integer")
        if isinstance(duration_minutes, int):
            return duration_minutes

        value = str(duration_minutes).strip()
        if not value.isdigit():
            raise ValueError("duration_minutes must be an integer")
        return int(value)

    @staticmethod
    def _require_non_empty(name: str, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{name} must not be empty")
        return text

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
