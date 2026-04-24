import asyncio
import json as json_module
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from proxy_scheduler import DynamicProxyGenerator
from proxy_scheduler_client import ClientCluster, Limits, ProxyClient, RequestSpec
from proxy_scheduler_client.response import Headers, Response
from proxy_scheduler_client.session import CookieRecord, SessionState
from proxy_scheduler_client.transport import Transport


class DemoTransport(Transport):
    """
    本地演示传输层，不发起真实网络请求。
    """

    def __init__(self, proxy_snapshot: str) -> None:
        """
        初始化演示传输层。

        Args:
            proxy_snapshot (str): 脱敏代理快照。

        Returns:
            None: 无返回值。
        """

        self.proxy_snapshot = proxy_snapshot
        self.cookies: list[CookieRecord] = []

    async def request(self, spec: RequestSpec, state: SessionState) -> Response:
        """
        模拟执行异步请求。

        Args:
            spec (RequestSpec): 请求规格。
            state (SessionState): 会话状态。

        Returns:
            Response: 模拟响应对象。
        """

        payload = {
            "url": spec.url,
            "method": spec.method.upper(),
            "tag": spec.tag,
            "headers": {**state.default_headers, **state.headers_sticky, **(spec.headers or {})},
            "proxy": self.proxy_snapshot,
            "local_storage": dict(state.local_storage),
        }
        return Response(
            status=200,
            headers=Headers(items=[("content-type", "application/json")]),
            url=spec.url,
            final_url=spec.url,
            method=spec.method.upper(),
            elapsed_ms=1.0,
            request_tag=spec.tag,
            content=json_module.dumps(payload, ensure_ascii=False).encode("utf-8"),
            encoding="utf-8",
            proxy_snapshot=self.proxy_snapshot,
        )

    async def close(self) -> None:
        """
        关闭演示传输层。

        Returns:
            None: 无返回值。
        """

        return None

    def export_cookies(self) -> list[CookieRecord]:
        """
        导出演示 Cookie。

        Returns:
            list[CookieRecord]: Cookie 列表。
        """

        return list(self.cookies)

    def import_cookies(self, cookies: list[CookieRecord], *, merge: bool = True) -> None:
        """
        导入演示 Cookie。

        Args:
            cookies (list[CookieRecord]): Cookie 列表。
            merge (bool): 是否合并已有 Cookie。

        Returns:
            None: 无返回值。
        """

        if not merge:
            self.cookies.clear()
        self.cookies.extend(cookies)


async def main() -> None:
    """
    演示动态代理生成器与异步客户端分离后的并发调用方式。

    Args:
        无。

    Returns:
        None: 无返回值。
    """

    # =========================
    # 1. 加载项目 .env 配置
    # 2. 创建动态代理生成器
    # 3. 批量生成代理地址
    # 4. 创建多客户端集群
    # 5. 并发执行请求
    # 6. 输出响应结果
    # =========================
    env_path = ROOT / ".env"
    if env_path.exists():
        print(f"[客户端示例] 读取项目环境文件 - path: {env_path}")
        for line in env_path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text or text.startswith("#") or "=" not in text:
                continue
            key, value = text.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    else:
        print(f"[客户端示例] 未找到项目环境文件 - path: {env_path}")

    user_id = os.environ.get("IPWEB_USER_ID", "B_DEMO").strip()
    password = os.environ.get("IPWEB_PASSWORD", "YOUR_PASSWORD").strip()
    gateway = os.environ.get("IPWEB_GATEWAY", "global").strip()
    country_code = os.environ.get("IPWEB_COUNTRY_CODE", "US").strip()
    protocol = os.environ.get("IPWEB_PROTOCOL", "http").strip()
    request_url = os.environ.get("IPWEB_TEST_URL", "https://api.ipify.org?format=json").strip()

    print("[客户端示例] 读取系统环境完成")
    print(
        f"[客户端示例] 环境参数 - gateway: {gateway} country_code: {country_code} "
        f"protocol: {protocol} URL: {request_url}"
    )

    print("[客户端示例] 开始创建动态代理生成器")
    generator = DynamicProxyGenerator(
        user_id=user_id,
        password=password,
        gateway=gateway,
    )

    print("[客户端示例] 批量生成代理 - count: 3")
    proxies = generator.generate(
        count=3,
        country_code=country_code,
        duration_minutes=5,
        protocol=protocol,
    )

    clients: list[ProxyClient] = []
    for index, proxy in enumerate(proxies):
        print(f"[客户端示例] 创建客户端 - index: {index} proxy: {proxy.safe_proxy_url}")
        client = ProxyClient(
            proxy_url=proxy.proxy_url,
            limits=Limits(concurrency=2, connector_limit=10),
            transport=DemoTransport(proxy.safe_proxy_url),
            verbose=True,
            default_headers={"accept": "application/json"},
        )
        client.sticky_header("x-demo-session", proxy.session_state_hint())
        client.set_local("proxy_index", index)
        clients.append(client)

    requests = [
        RequestSpec(
            method="GET",
            url=request_url,
            headers={"x-request-index": str(index)},
            tag=f"demo-{index}",
        )
        for index in range(6)
    ]

    print("[客户端示例] 开始并发请求 - total: 6")
    async with ClientCluster(clients, verbose=True) as cluster:
        responses = await cluster.gather(requests)
        for response in responses:
            print(
                f"[客户端示例] 请求完成 - tag: {response.request_tag} "
                f"状态: {response.status} 成功: {response.ok} 代理: {response.proxy_snapshot}"
            )
            print(f"[客户端示例] 响应内容 - body: {response.text()}")
        print(f"[客户端示例] 指标快照 - metrics: {cluster.metrics_snapshot()}")


if __name__ == "__main__":
    asyncio.run(main())
