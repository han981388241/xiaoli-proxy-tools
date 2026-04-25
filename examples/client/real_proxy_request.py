import asyncio
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from proxy_scheduler import DynamicProxyGenerator
from proxy_scheduler_client import ClientCluster, Limits, ProxyClient, RequestSpec


async def main() -> None:
    """
    使用动态代理生成器为每个并发请求创建独立代理，并通过异步客户端发起真实网络请求。

    Args:
        无。

    Returns:
        None: 无返回值。

    Raises:
        RuntimeError: 缺少必要环境变量时抛出。
    """

    # =========================
    # 1. 加载项目 .env 配置
    # 2. 读取请求与代理参数
    # 3. 按请求数量批量生成真实代理
    # 4. 为每条代理创建独立异步客户端
    # 5. 并发发起真实请求
    # 6. 输出响应与指标
    # =========================
    env_path = ROOT / ".env"
    if env_path.exists():
        print(f"[真实请求示例] 读取项目环境文件 - path: {env_path}")
        for line in env_path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text or text.startswith("#") or "=" not in text:
                continue
            key, value = text.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    else:
        print(f"[真实请求示例] 未找到项目环境文件 - path: {env_path}")

    user_id = os.environ.get("IPWEB_USER_ID", "").strip()
    password = os.environ.get("IPWEB_PASSWORD", "").strip()
    gateway = os.environ.get("IPWEB_GATEWAY", "global").strip()
    country_code = os.environ.get("IPWEB_COUNTRY_CODE", "US").strip()
    state_code = os.environ.get("IPWEB_STATE_CODE", "").strip()
    city_code = os.environ.get("IPWEB_CITY_CODE", "").strip()
    protocol = os.environ.get("IPWEB_PROTOCOL", "http").strip()
    duration_minutes = int(os.environ.get("IPWEB_DURATION_MINUTES", "5").strip())
    request_url = os.environ.get("IPWEB_TEST_URL", "https://api.ipify.org?format=json").strip()
    request_count = int(os.environ.get("IPWEB_TEST_REQUEST_COUNT", "10").strip())
    concurrency = int(os.environ.get("IPWEB_TEST_CONCURRENCY", "10").strip())
    timeout = float(os.environ.get("IPWEB_TEST_TIMEOUT", "30").strip())
    verify = os.environ.get("IPWEB_VERIFY", "false").strip().lower() not in {"0", "false", "no"}

    print("[真实请求示例] 读取系统环境完成")
    print(
        f"[真实请求示例] 请求参数 - URL: {request_url} gateway: {gateway} "
        f"country_code: {country_code} protocol: {protocol} count: {request_count} "
        f"concurrency: {concurrency} timeout: {timeout} verify: {verify}"
    )

    if not user_id or not password:
        raise RuntimeError("请先设置 IPWEB_USER_ID 和 IPWEB_PASSWORD 环境变量")
    if request_count <= 0:
        raise RuntimeError("IPWEB_TEST_REQUEST_COUNT 必须大于 0")
    if concurrency <= 0:
        raise RuntimeError("IPWEB_TEST_CONCURRENCY 必须大于 0")

    print("[真实请求示例] 开始创建动态代理生成器")
    generator = DynamicProxyGenerator(
        user_id=user_id,
        password=password,
        gateway=gateway,
    )

    print(
        f"[真实请求示例] 开始批量生成代理 - count: {request_count} "
        f"country_code: {country_code} protocol: {protocol}"
    )
    proxies = generator.generate(
        count=request_count,
        country_code=country_code,
        state_code=state_code,
        city_code=city_code,
        duration_minutes=duration_minutes,
        protocol=protocol,
    )
    if not isinstance(proxies, list):
        proxies = [proxies]

    for index, proxy in enumerate(proxies):
        print(
            f"[真实请求示例] 代理生成完成 - index: {index} "
            f"session_id: {proxy.session_id} proxy: {proxy.safe_proxy_url}"
        )

    requests = [
        RequestSpec(
            method="GET",
            url=request_url,
            headers={
                "Accept": "application/json,text/plain,*/*",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
            },
            timeout=timeout,
            # tag=f"real-test-{index}",
            # meta={"verify": verify},
        )
        for index in range(request_count)
    ]

    clients: list[ProxyClient] = []
    for index, proxy in enumerate(proxies):
        print(f"[真实请求示例] 创建独立客户端 - index: {index} proxy: {proxy.safe_proxy_url}")
        client = ProxyClient(
            proxy_url=proxy.proxy_url,
            limits=Limits(
                concurrency=1,
                connector_limit=1,
                connector_limit_per_host=0,
                connect_timeout=min(timeout, 10.0),
                read_timeout=timeout,
                total_timeout=timeout,
            ),
            verbose=True,
            default_headers={"accept-language": "en-US,en;q=0.9"},
        )
        # client.sticky_header("x-ipweb-session", proxy.session_state_hint())
        clients.append(client)

    print(
        f"[真实请求示例] 开始真实并发请求 - URL: {request_url} "
        f"请求数: {len(requests)} 独立代理数: {len(clients)}"
    )
    async with ClientCluster(clients, verbose=True) as cluster:
        responses = await cluster.gather(requests, return_exceptions=True)

        for response in responses:
            if response.error:
                print(
                    f"[真实请求示例] 请求失败 - URL: {response.url} 状态: {response.status} "
                    f"tag: {response.request_tag} 代理: {response.proxy_snapshot} "
                    f"错误类型: {type(response.error).__name__} 错误: {response.error}"
                )
                response.close()
                continue

            body = response.text()
            if len(body) > 500:
                body = body[:500] + "...[已截断]"
            print(
                f"[真实请求示例] 请求成功 - URL: {response.final_url} 状态: {response.status} "
                f"tag: {response.request_tag} 耗时: {response.elapsed_ms:.2f}ms "
                f"代理: {response.proxy_snapshot} 响应: {body}"
            )
            response.close()

        print(f"[真实请求示例] 集群指标快照 - metrics: {cluster.metrics_snapshot()}")


if __name__ == "__main__":
    asyncio.run(main())
