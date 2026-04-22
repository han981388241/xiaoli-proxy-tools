"""
Standalone dynamic proxy generation channel.

This module is intentionally independent from the request executor. Use it
when you only need a fresh IPWeb proxy URL/proxies dict and do not want the
SDK to send a request.
"""

from __future__ import annotations

from typing import Iterable, overload, Literal

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

    @overload
    def generate(
        self,
        *,
        count: Literal[1] = 1,
        country_code: str = "000",
        duration_minutes: int = 5,
        session_id: str | None = None,
        state_code: str = "",
        city_code: str = "",
        protocol: str = "http",
    ) -> PreparedProxy:
        ...

    @overload
    def generate(
        self,
        *,
        count: int,
        country_code: str = "000",
        duration_minutes: int = 5,
        session_id: str | None = None,
        state_code: str = "",
        city_code: str = "",
        protocol: str = "http",
    ) -> PreparedProxy | list[PreparedProxy]:
        ...

    def generate(
        self,
        *,
        count: int = 1,
        country_code: str = "000",
        duration_minutes: int = 5,
        session_id: str | None = None,
        state_code: str = "",
        city_code: str = "",
        protocol: str = "http",
    ) -> PreparedProxy | list[PreparedProxy]:
        """
        Generate one or many dynamic proxy identities from a single entry point.

        count=1  -> PreparedProxy
        count>1  -> list[PreparedProxy]
        count=0  -> []
        """

        if count < 0:
            raise ValueError("count must be >= 0")
        if count == 0:
            return []
        if count > 1:
            if session_id is not None:
                raise ValueError("session_id cannot be used when count > 1")
            return self.client.build_proxy_many(
                count,
                country_code=country_code,
                duration_minutes=duration_minutes,
                state_code=state_code,
                city_code=city_code,
                protocol=protocol,
                validate=True,
            )

        normalized_duration = self.client._normalize_duration(duration_minutes)
        return self.client.build_proxy(
            country_code=country_code,
            duration_minutes=normalized_duration,
            session_id=session_id,
            state_code=state_code,
            city_code=city_code,
            protocol=protocol,
            validate=True,
        )

    def generate_many(
        self,
        count: int,
        *,
        country_code: str = "000",
        duration_minutes: int = 5,
        state_code: str = "",
        city_code: str = "",
        protocol: str = "http",
    ) -> list[PreparedProxy]:
        """Compatibility wrapper around generate(count=...)."""

        result = self.generate(
            count=count,
            country_code=country_code,
            duration_minutes=duration_minutes,
            session_id=None,
            state_code=state_code,
            city_code=city_code,
            protocol=protocol,
        )
        return result if isinstance(result, list) else [result]

    def generate_node(
        self,
        *,
        country_code: str = "000",
        duration_minutes: int = 5,
        session_id: str | None = None,
        state_code: str = "",
        city_code: str = "",
        protocol: str = "http",
    ) -> ProxyNode:
        """
        Generate one ProxyNode-shaped object for advanced integrations.

        This is just a structured proxy container used by the executor.
        """

        normalized_duration = self.client._normalize_duration(duration_minutes)
        sid = session_id or generate_session_id()
        prepared = self.generate(
            count=1,
            country_code=country_code,
            duration_minutes=normalized_duration,
            session_id=sid,
            state_code=state_code,
            city_code=city_code,
            protocol=protocol,
        )
        assert isinstance(prepared, PreparedProxy)
        return ProxyNode(
            session_id=sid,
            proxy_url=prepared.proxy_url,
            proxies=prepared.proxies,
            country_code=country_code,
            duration_minutes=normalized_duration,
        )

    @staticmethod
    def proxy_urls(
        proxies: Iterable[PreparedProxy],
        protocol: str = "http",
    ) -> list[str]:
        """Extract proxy URLs from generated proxy objects for a target protocol."""

        return [proxy.url_for(protocol) for proxy in proxies]
