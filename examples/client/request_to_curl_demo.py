import asyncio
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from proxy_scheduler import DynamicProxyGenerator
from proxy_scheduler_client import Limits, ProxyClient, RequestSpec
from proxy_scheduler_client.session import CookieRecord


async def main() -> None:
    """
    演示如何将异步请求规格和客户端最终请求导出为单行 curl 命令。

    Args:
        无。

    Returns:
        None: 无返回值。

    Raises:
        RuntimeError: 缺少必要环境变量时抛出。
    """

    # =========================
    # 1. 加载项目 .env 配置
    # 2. 读取代理与请求参数
    # 3. 创建动态代理生成器并生成单条代理
    # 4. 演示 RequestSpec.to_curl()
    # 5. 演示 ProxyClient.request_to_curl()
    # 6. 输出单行 curl 命令
    # =========================
    env_path = ROOT / ".env"
    if env_path.exists():
        print(f"[Curl示例] 读取项目环境文件 - path: {env_path}")
        for line in env_path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text or text.startswith("#") or "=" not in text:
                continue
            key, value = text.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    else:
        print(f"[Curl示例] 未找到项目环境文件 - path: {env_path}")

    user_id = os.environ.get("IPWEB_USER_ID", "").strip()
    password = os.environ.get("IPWEB_PASSWORD", "").strip()
    gateway = os.environ.get("IPWEB_GATEWAY", "global").strip()
    country_code = os.environ.get("IPWEB_COUNTRY_CODE", "US").strip()
    protocol = os.environ.get("IPWEB_PROTOCOL", "http").strip()
    request_url = os.environ.get("IPWEB_TEST_URL", "https://api.ipify.org?format=json").strip()
    duration_minutes = int(os.environ.get("IPWEB_DURATION_MINUTES", "5").strip())

    print("[Curl示例] 读取系统环境完成")
    print(
        f"[Curl示例] 环境参数 - gateway: {gateway} country_code: {country_code} "
        f"protocol: {protocol} URL: {request_url}"
    )

    if not user_id or not password:
        raise RuntimeError("请先设置 IPWEB_USER_ID 和 IPWEB_PASSWORD 环境变量")

    print("[Curl示例] 开始创建动态代理生成器")
    generator = DynamicProxyGenerator(
        user_id=user_id,
        password=password,
        gateway=gateway,
    )

    print("[Curl示例] 开始生成单条代理")
    proxy = generator.generate(
        country_code=country_code,
        duration_minutes=duration_minutes,
        protocol=protocol,
    )
    print(f"[Curl示例] 代理生成完成 - proxy: {proxy.safe_proxy_url}")

    spec = RequestSpec(
        method="GET",
        url=request_url,
        headers={
            "Accept": "application/json,text/plain,*/*",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
            ),
        },
        # params={"scene": "demo", "token": "sensitive-query-token"},
        # json={"message": "hello", "password": "secret-password"},
        # timeout=20,
        # tag="curl-spec-demo",
        # meta={
        #     "allow_redirects": True,
        #     "verify": False,
        #     "cookies": {"spec_cookie": "spec-cookie-value"},
        #     "proxy_headers": {"X-Proxy-Token": "proxy-secret-token"},
        #     "auth": ("spec-user", "spec-password"),
        # },
    )

    print("[Curl示例] 开始导出 RequestSpec 单行 curl 命令 - shell: cmd")
    spec_curl_cmd = spec.to_curl(
        masked=False,
        shell="cmd",
        proxy_url=proxy.proxy_url,
        # cookies={"base_cookie": "base-cookie-value"},
    )
    print("[Curl示例] RequestSpec cmd 单行脱敏 curl 如下：")
    print(spec_curl_cmd)

    print("[Curl示例] 开始导出 RequestSpec 单行 curl 命令 - shell: powershell")
    spec_curl_powershell = spec.to_curl(
        masked=False,
        shell="powershell",
        proxy_url=proxy.proxy_url,
        # cookies={"base_cookie": "base-cookie-value"},
    )
    print("[Curl示例] RequestSpec PowerShell 单行脱敏 curl 如下：")
    print(spec_curl_powershell)

    print("[Curl示例] 开始创建异步客户端并注入会话头与 Cookie")
    async with ProxyClient(
        proxy_url=proxy.proxy_url,
        limits=Limits(concurrency=1, connector_limit=1),
        default_headers={"Accept-Language": "en-US,en;q=0.9"},
        user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
            ),
        verbose=False,
    ) as client:
        # client.sticky_header("X-Session-Hint", proxy.session_state_hint())
        # client.set_cookie(CookieRecord(name="", value=""))
        resp = await client.request(
            spec
        )
        print(resp.text())
        print("[Curl示例] 开始导出 ProxyClient 最终请求单行 curl 命令 - shell: cmd")
        client_curl_cmd = client.request_to_curl(
            spec
        )
        print("[Curl示例] ProxyClient cmd 单行脱敏 curl 如下：")
        print(client_curl_cmd)

        print("[Curl示例] 开始导出 ProxyClient 最终请求单行 curl 命令 - shell: powershell")
        client_curl_powershell = client.request_to_curl(
            spec
        )
        print("[Curl示例] ProxyClient PowerShell 单行脱敏 curl 如下：")
        print(client_curl_powershell)

    print("[Curl示例] 输出完成")


if __name__ == "__main__":
    asyncio.run(main())
