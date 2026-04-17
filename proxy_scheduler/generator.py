"""
Standalone dynamic proxy generation channel.

This module is intentionally independent from the request executor. Use it
when you only need a fresh IPWeb proxy URL/proxies dict and do not want the
SDK to send a request.
"""

from __future__ import annotations

from typing import Iterable

from .core.models import ProxyNode
from .ipweb import DynamicProxyClient, Gateway, PreparedProxy, generate_session_id


class DynamicProxyGenerator:
    """Generate IPWeb dynamic proxy credentials without starting a pool."""

    def __init__(
        self,
        *,
        user_id: str,
        password: str,
        gateway: str = "apac",
        client: DynamicProxyClient | None = None,
    ) -> None:
        self.client = client or DynamicProxyClient(
            user_id=user_id,
            password=password,
            gateway=Gateway.normalize(gateway),
        )

    def generate(
        self,
        *,
        country_code: str = "000",
        duration_minutes: int = 5,
        session_id: str | None = None,
        state_code: str = "",
        city_code: str = "",
    ) -> PreparedProxy:
        """Generate one dynamic proxy identity."""

        return self.client.build_proxy(
            country_code=country_code,
            duration_minutes=duration_minutes,
            session_id=session_id or generate_session_id(),
            state_code=state_code,
            city_code=city_code,
            validate=False,
        )

    def generate_many(
        self,
        count: int,
        *,
        country_code: str = "000",
        duration_minutes: int = 5,
        state_code: str = "",
        city_code: str = "",
    ) -> list[PreparedProxy]:
        """Generate multiple independent proxy identities."""

        if count < 0:
            raise ValueError("count must be >= 0")

        return [
            self.generate(
                country_code=country_code,
                duration_minutes=duration_minutes,
                state_code=state_code,
                city_code=city_code,
            )
            for _ in range(count)
        ]

    def generate_node(
        self,
        *,
        country_code: str = "000",
        duration_minutes: int = 5,
        session_id: str | None = None,
        state_code: str = "",
        city_code: str = "",
    ) -> ProxyNode:
        """
        Generate one ProxyNode-shaped object for advanced integrations.

        This is just a structured proxy container used by the executor.
        """

        sid = session_id or generate_session_id()
        prepared = self.generate(
            country_code=country_code,
            duration_minutes=duration_minutes,
            session_id=sid,
            state_code=state_code,
            city_code=city_code,
        )
        return ProxyNode(
            session_id=sid,
            proxy_url=prepared.proxy_url,
            proxies=prepared.proxies,
            country_code=country_code,
            duration_minutes=duration_minutes,
        )

    @staticmethod
    def proxy_urls(proxies: Iterable[PreparedProxy]) -> list[str]:
        """Extract proxy URLs from generated proxy objects."""

        return [proxy.proxy_url for proxy in proxies]
