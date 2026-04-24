"""
动态代理生成器对外入口模块。

本模块提供单条、批量、迭代式代理生成能力，以及国家、州、城市代码查询能力。
"""

from __future__ import annotations

from typing import Iterable, Iterator

from .core import DynamicProxyClient, Gateway, PreparedProxy
from .geo import load_geo_index


class DynamicProxyGenerator:
    """
    IPWEB 动态代理生成器。
    """

    def __init__(
        self,
        *,
        user_id: str,
        password: str,
        gateway: str = "apac",
        client: DynamicProxyClient | None = None,
    ) -> None:
        """
        初始化动态代理生成器。

        Args:
            user_id (str): IPWEB 代理账号用户标识。
            password (str): IPWEB 代理账号密码。
            gateway (str): IPWEB 官方网关别名或官方网关地址。
            client (DynamicProxyClient | None): 可选的底层代理地址构建器。

        Raises:
            ValueError: 账号、密码或网关不合法时抛出。
        """

        self.client = client or DynamicProxyClient(
            user_id=user_id,
            password=password,
            gateway=Gateway.normalize(gateway),
        )

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
        统一生成动态代理，单条和批量都通过此入口完成。

        Args:
            count (int): 生成数量，1 返回单个对象，大于 1 返回列表。
            country_code (str): 国家代码，000 表示不限国家。
            duration_minutes (int): 会话时长，单位为分钟。
            session_id (str | None): 自定义会话标识，仅单条生成时可用。
            state_code (str): 州代码。
            city_code (str): 城市代码。
            protocol (str): 主代理协议。

        Returns:
            PreparedProxy | list[PreparedProxy]: 单条或多条代理对象。

        Raises:
            ValueError: 参数不合法时抛出。
        """

        count = self.client._normalize_count(count)
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

    def iter_generate(
        self,
        *,
        count: int,
        country_code: str = "000",
        duration_minutes: int = 5,
        state_code: str = "",
        city_code: str = "",
        protocol: str = "http",
    ) -> Iterator[PreparedProxy]:
        """
        迭代式生成动态代理，适合大批量低内存场景。

        Args:
            count (int): 生成数量。
            country_code (str): 国家代码，000 表示不限国家。
            duration_minutes (int): 会话时长，单位为分钟。
            state_code (str): 州代码。
            city_code (str): 城市代码。
            protocol (str): 主代理协议。

        Yields:
            PreparedProxy: 动态代理对象。

        Raises:
            ValueError: 参数不合法时抛出。
        """

        yield from self.client.iter_build_proxy(
            count,
            country_code=country_code,
            duration_minutes=duration_minutes,
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
        """
        兼容旧版本的批量生成方法，新代码建议直接使用 generate(count=...)。

        Args:
            count (int): 生成数量。
            country_code (str): 国家代码，000 表示不限国家。
            duration_minutes (int): 会话时长，单位为分钟。
            state_code (str): 州代码。
            city_code (str): 城市代码。
            protocol (str): 主代理协议。

        Returns:
            list[PreparedProxy]: 动态代理对象列表。

        Raises:
            ValueError: 参数不合法时抛出。
        """

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

    def list_countries(self) -> list[str]:
        """
        返回 SDK 内置地区数据支持的国家代码列表。

        Returns:
            list[str]: 国家代码列表。
        """

        geo = load_geo_index()
        return sorted(geo.countries)

    def list_states(self, country_code: str) -> list[str]:
        """
        返回指定国家支持的州代码列表。

        Args:
            country_code (str): 国家代码。

        Returns:
            list[str]: 州代码列表。

        Raises:
            ValueError: 国家代码不合法或不支持时抛出。
        """

        country = self._require_supported_country(country_code)
        geo = load_geo_index()
        return sorted(geo.states_by_country.get(country, frozenset()))

    def list_cities(self, country_code: str, state_code: str = "") -> list[str]:
        """
        返回指定国家或指定州支持的城市代码列表。

        Args:
            country_code (str): 国家代码。
            state_code (str): 州代码，为空时返回该国家全部城市代码。

        Returns:
            list[str]: 城市代码列表。

        Raises:
            ValueError: 国家或州代码不合法时抛出。
        """

        country = self._require_supported_country(country_code)
        state = self.client.normalize_location_code(state_code)
        geo = load_geo_index()

        if not state:
            return sorted(geo.cities_by_country.get(country, frozenset()))

        states = geo.states_by_country.get(country, frozenset())
        if state not in states:
            raise ValueError(f"invalid state_code {state!r} for country_code {country!r}")

        city_to_state = geo.city_to_state_by_country.get(country, {})
        return sorted(city for city, city_state in city_to_state.items() if city_state == state)

    @staticmethod
    def proxy_urls(
        proxies: Iterable[PreparedProxy],
        protocol: str = "http",
    ) -> list[str]:
        """
        从代理对象列表中提取指定协议的代理地址。

        Args:
            proxies (Iterable[PreparedProxy]): 代理对象集合。
            protocol (str): 目标代理协议。

        Returns:
            list[str]: 代理地址列表。

        Raises:
            ValueError: 协议不支持时抛出。
        """

        return [proxy.url_for(protocol) for proxy in proxies]

    def _require_supported_country(self, country_code: str) -> str:
        """
        校验国家代码是否在内置地区数据中。

        Args:
            country_code (str): 原始国家代码。

        Returns:
            str: 标准化后的国家代码。

        Raises:
            ValueError: 国家代码不合法或不支持时抛出。
        """

        country = self.client.normalize_country_code(country_code)
        if country == "000":
            raise ValueError("country_code must be a specific country code, not '000'")
        if not country or len(country) != 2:
            raise ValueError("country_code must be a 2-letter ISO country code")

        geo = load_geo_index()
        if country not in geo.countries:
            raise ValueError(f"unsupported country_code: {country}")
        return country
