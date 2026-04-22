"""
Small IPWeb tunnel adapter used when the external ipweb_proxy_sdk package
is not installed.

IPWeb's documented self-defined account format is:
    user_id_country_state_city_duration_sid

Example without state/city restrictions:
    B_36424_US___5_Ab000001
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from urllib.parse import quote, unquote, urlsplit
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
_CLIENT_ALIASES = {
    "request": "requests",
    "requests": "requests",
    "httpx": "httpx",
    "aiohttp": "aiohttp",
    "aiohttp-socks": "aiohttp_socks",
    "aiohttp_socks": "aiohttp_socks",
    "playwright": "playwright",
}
logger = logging.getLogger(__name__)


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
    proxy_url: str
    proxies: dict[str, str]
    username: str
    gateway: str

    @property
    def http_url(self) -> str:
        return self.proxies["http"]

    @property
    def https_url(self) -> str:
        return self.proxies["https"]

    @property
    def socks5_url(self) -> str:
        return self.proxies["socks5"]

    @property
    def socks5h_url(self) -> str:
        return self.proxies["socks5h"]

    def url_for(self, protocol: str = "http") -> str:
        normalized = DynamicProxyClient.normalize_protocol(protocol)
        return self.proxies[normalized]

    def for_client(self, client: str, protocol: str = "http") -> dict[str, object]:
        """
        生成不同客户端可直接使用的代理配置。

        Args:
            client (str): 客户端名称，支持 requests、httpx、aiohttp、aiohttp_socks、playwright。
            protocol (str): 代理协议，支持 http、https、socks5、socks5h。

        Returns:
            dict[str, object]: 对应客户端可直接展开使用的代理参数字典。

        Raises:
            ValueError: 当客户端类型不支持，或客户端与代理协议组合不兼容时抛出。
            ImportError: 当使用 aiohttp_socks 但未安装 aiohttp-socks 依赖时抛出。
        """

        normalized_client = self._normalize_client(client)
        proxy_url = self.url_for(protocol)
        logger.debug(
            "[代理适配] 生成客户端代理参数 - client=%s protocol=%s gateway=%s",
            normalized_client,
            DynamicProxyClient.normalize_protocol(protocol),
            self.gateway,
        )

        if normalized_client == "requests":
            return {"http": proxy_url, "https": proxy_url}

        if normalized_client == "httpx":
            return {"proxy": proxy_url}

        if normalized_client == "aiohttp":
            normalized_protocol = DynamicProxyClient.normalize_protocol(protocol)
            if normalized_protocol in {"socks5", "socks5h"}:
                raise ValueError(
                    "aiohttp 原生只支持 HTTP 代理，请改用 client='aiohttp_socks' 处理 SOCKS 代理"
                )
            return {"proxy": proxy_url}

        if normalized_client == "aiohttp_socks":
            try:
                from aiohttp_socks import ProxyConnector
            except ImportError as exc:
                raise ImportError(
                    "aiohttp-socks is not installed. Run: pip install aiohttp-socks"
                ) from exc
            return {"connector": ProxyConnector.from_url(proxy_url)}

        if normalized_client == "playwright":
            return self._playwright_proxy(proxy_url)

        raise ValueError(f"unsupported proxy client: {client!r}")

    @staticmethod
    def _normalize_client(client: str) -> str:
        key = str(client or "").strip().lower()
        try:
            return _CLIENT_ALIASES[key]
        except KeyError as exc:
            supported = ", ".join(sorted(_CLIENT_ALIASES))
            raise ValueError(
                f"unsupported proxy client: {client!r}. Supported: {supported}"
            ) from exc

    @staticmethod
    def _playwright_proxy(proxy_url: str) -> dict[str, str]:
        parsed = urlsplit(proxy_url)
        if not parsed.hostname or parsed.port is None:
            raise ValueError(f"invalid proxy url for Playwright: {proxy_url!r}")

        result = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}
        if parsed.username:
            result["username"] = unquote(parsed.username)
        if parsed.password:
            result["password"] = unquote(parsed.password)
        return result


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
