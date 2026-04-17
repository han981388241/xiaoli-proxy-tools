"""
Small IPWeb tunnel adapter used when the external ipweb_proxy_sdk package
is not installed.

IPWeb's documented self-defined account format is:
    user_id_country_state_city_duration_sid

Example without state/city restrictions:
    B_36424_US___5_Ab000001
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from urllib.parse import quote


DEFAULT_PORT = 7778


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


def generate_session_id() -> str:
    """Return an IPWeb-compatible 8-character SID."""

    return uuid.uuid4().hex


class DynamicProxyClient:
    """Build IPWeb HTTP/S proxy URLs from account credentials."""

    def __init__(self, *, user_id: str, password: str, gateway: str = "apac") -> None:
        self.user_id = user_id
        self.password = password
        self.gateway = Gateway.normalize(gateway)

    def build_proxy(
        self,
        *,
        country_code: str = "000",
        duration_minutes: int = 5,
        session_id: str | None = None,
        state_code: str = "",
        city_code: str = "",
        validate: bool = False,
    ) -> PreparedProxy:
        sid = session_id or generate_session_id()
        country = (country_code or "000").upper()
        username = (
            f"{self.user_id}_{country}_{state_code}_{city_code}_"
            f"{duration_minutes}_{sid}"
        )
        proxy_url = self._build_proxy_url(username)
        return PreparedProxy(
            proxy_url=proxy_url,
            proxies={"http": proxy_url, "https": proxy_url},
            username=username,
            gateway=self.gateway,
        )

    def _build_proxy_url(self, username: str) -> str:
        encoded_user = quote(username, safe="")
        encoded_password = quote(self.password, safe="")
        return f"http://{encoded_user}:{encoded_password}@{self.gateway}"
