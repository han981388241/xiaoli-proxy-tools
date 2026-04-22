import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from proxy_client import AsyncProxyClient, async_requests_request_retry
from proxy_scheduler import DynamicProxyGenerator


async def main() -> None:
    """
    演示通用异步代理客户端的几种常见调用方式。

    Returns:
        None: 无返回值。

    Raises:
        Exception: 当网络请求异常时抛出。
    """

    # =========================
    # 1. 构建演示参数
    # 2. 演示直连请求
    # 3. 演示固定代理请求
    # 4. 演示动态代理生成器请求
    # 5. 演示兼容包装函数请求
    # 6. 返回结果
    # =========================
    target_url = "https://api.ipify.org?format=json"
    external_proxy_url = "http://YOU_PROXY_USERNAME:YOU_PROXY_PASSWORD@127.0.0.1:8080"
    user_id = "YOU_USER_ID"
    password = "YOU_USER_PASSWORD"
    gateway = "apac"

    print(f"[客户端示例] 开始执行 - URL: {target_url}")

    print(f"[客户端示例] 直连模式开始 - URL: {target_url}")
    async with AsyncProxyClient(
        retry_count=2,
        base_delay=1.0,
        max_delay=3.0,
        verbose=True,
    ) as client:
        response = await client.get(
            target_url,
            timeout=30,
            verify=False,
            impersonate="chrome124",
        )
        print(
            f"[客户端示例] 直连模式完成 - 状态: {response.status_code} "
            f"响应: {response.text}"
        )

    print(f"[客户端示例] 固定代理模式开始 - URL: {target_url}")
    if "YOU_PROXY_" in external_proxy_url:
        print(
            "[客户端示例] 固定代理模式跳过 - 原因: 未填写 external_proxy_url，"
            "请替换为真实代理地址后再执行"
        )
    else:
        async with AsyncProxyClient(
            proxy_source=external_proxy_url,
            retry_count=2,
            base_delay=1.0,
            max_delay=3.0,
            verbose=True,
        ) as client:
            response = await client.get(
                target_url,
                timeout=30,
                verify=False,
                impersonate="chrome124",
            )
            print(
                f"[客户端示例] 固定代理模式完成 - 状态: {response.status_code} "
                f"响应: {response.text}"
            )

    print(f"[客户端示例] 动态代理模式开始 - URL: {target_url}")
    if "YOU_" in user_id or "YOU_" in password:
        print(
            "[客户端示例] 动态代理模式跳过 - 原因: 未填写 user_id/password，"
            "请替换为真实账号后再执行"
        )
    else:
        generator = DynamicProxyGenerator(
            user_id=user_id,
            password=password,
            gateway=gateway,
        )
        prepared_proxy = generator.generate(
            country_code="US",
            protocol="http",
        )
        print(f"[客户端示例] 已生成动态代理 - proxy_url: {prepared_proxy.proxy_url}")

        async with AsyncProxyClient(
            proxy_source=prepared_proxy.socks5h_url,
            retry_count=2,
            base_delay=1.0,
            max_delay=3.0,
            verbose=True,
        ) as client:
            response = await client.get(
                target_url,
                timeout=30,
                verify=False,
                impersonate="chrome124",
            )
            print(
                f"[客户端示例] 动态代理模式完成 - 状态: {response.status_code} "
                f"响应: {response.text}"
            )

        print(f"[客户端示例] 兼容包装函数模式开始 - URL: {target_url}")
        response = await async_requests_request_retry(
            "GET",
            target_url,
            proxy_source=prepared_proxy.socks5_url,
            timeout=30,
            verify=False,
            impersonate="chrome124",
            max_retries=2,
            base_delay=1.0,
            max_delay=3.0,
            verbose=True,
        )
        print(
            f"[客户端示例] 兼容包装函数模式完成 - 状态: {response.status_code} "
            f"响应: {response.text}"
        )

    print("[客户端示例] 执行结束")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
