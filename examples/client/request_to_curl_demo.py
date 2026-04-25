import asyncio
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from proxy_scheduler import DynamicProxyGenerator
from proxy_scheduler_client import Limits, ProxyClient, RequestSpec


def load_env() -> None:
    """
    读取项目根目录下的 .env 文件并写入进程环境变量。

    Returns:
        None: 无返回值。
    """

    env_path = ROOT / ".env"
    if not env_path.exists():
        print(f"[Curl示例] 未找到项目环境文件 - path: {env_path}")
        return
    print(f"[Curl示例] 读取项目环境文件 - path: {env_path}")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def print_curl(label: str, command: str) -> None:
    """
    打印导出后的 curl 命令并以分隔线包裹便于复制。

    Args:
        label (str): 命令说明。
        command (str): curl 命令字符串。

    Returns:
        None: 无返回值。
    """

    print(f"[Curl示例] {label}")
    print("-" * 60)
    print(command)
    print("-" * 60)


async def main() -> None:
    """
    演示如何将异步请求规格和客户端最终请求导出为单行 curl 命令。

    Returns:
        None: 无返回值。

    Raises:
        RuntimeError: 缺少必要环境变量时抛出。
    """

    # =========================
    # 1. 加载项目 .env 配置
    # 2. 读取代理与请求参数
    # 3. 创建动态代理生成器并生成单条代理
    # 4. 演示 RequestSpec.to_curl(bash / powershell / cmd)
    # 5. 演示 ProxyClient.request_to_curl 注入 sticky header / cookies
    # 6. 真实发起一次请求验证
    # =========================
    load_env()

    user_id = os.environ.get("IPWEB_USER_ID", "").strip()
    password = os.environ.get("IPWEB_PASSWORD", "").strip()
    gateway = os.environ.get("IPWEB_GATEWAY", "global").strip()
    country_code = os.environ.get("IPWEB_COUNTRY_CODE", "US").strip()
    protocol = os.environ.get("IPWEB_PROTOCOL", "http").strip()
    request_url = os.environ.get("IPWEB_TEST_URL", "https://ipinfo.io/json").strip()
    duration_minutes = int(os.environ.get("IPWEB_DURATION_MINUTES", "5").strip())
    do_real_request = os.environ.get("IPWEB_CURL_DEMO_REAL", "1").strip().lower() not in {"0", "false", "no"}

    if not user_id or not password:
        raise RuntimeError("请先设置 IPWEB_USER_ID 和 IPWEB_PASSWORD 环境变量")

    print("[Curl示例] 读取系统环境完成")
    print(
        f"[Curl示例] 环境参数 - gateway: {gateway} country_code: {country_code} "
        f"protocol: {protocol} URL: {request_url} 真实请求: {do_real_request}"
    )

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
    print(f"[Curl示例] 代理生成完成 - safe: {proxy.safe_proxy_url} session_id: {proxy.session_id}")

    proxy_url = proxy.socks5_url
    print(proxy_url)
    print(f"[Curl示例] 当前协议代理地址 - protocol: {protocol} proxy_url: {proxy.safe_proxy_url}")

    spec = RequestSpec(
        method="GET",
        url=request_url,
        headers={
            "Accept": "application/json,text/plain,*/*",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        },
        timeout=20.0,
        tag="curl-spec-demo",
        meta={
            "allow_redirects": True,
            "verify": True,
        },
    )

    # ---- RequestSpec.to_curl 三套终端 ----
    print_curl(
        "RequestSpec.to_curl bash 单行（推荐：跨平台最稳，含 git-bash / WSL / macOS / Linux）",
        spec.to_curl(
            shell="bash",
            proxy_url=proxy_url,
            connect_timeout=10.0,
        ),
    )
    print_curl(
        "RequestSpec.to_curl powershell 单行（自动注入 curl.exe + --%）",
        spec.to_curl(
            shell="powershell",
            proxy_url=proxy_url,
            connect_timeout=10.0,
        ),
    )
    print_curl(
        "RequestSpec.to_curl cmd 单行（双引号转义 / %% 转义）",
        spec.to_curl(
            shell="cmd",
            proxy_url=proxy_url,
            connect_timeout=10.0,
        ),
    )
    print_curl(
        "RequestSpec.to_curl 脱敏版本（masked=True，仅供贴日志，不可直接执行）",
        spec.to_curl(
            shell="bash",
            masked=True,
            proxy_url=proxy_url,
            connect_timeout=10.0,
        ),
    )

    # ---- ProxyClient.request_to_curl ----
    print("[Curl示例] 开始构建 ProxyClient（注入 sticky header / 默认 UA）")
    async with ProxyClient(
        proxy_url=proxy_url,
        limits=Limits(
            concurrency=1,
            connector_limit=1,
            connect_timeout=10.0,
            read_timeout=20.0,
            total_timeout=30.0,
        ),
        default_headers={"Accept-Language": "en-US,en;q=0.9"},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        verbose=False,
    ) as client:
        print_curl(
            "ProxyClient.request_to_curl bash 单行（合并 default_headers / sticky / cookies / Limits.connect_timeout）",
            client.request_to_curl(spec, shell="bash"),
        )
        print_curl(
            "ProxyClient.request_to_curl powershell 单行",
            client.request_to_curl(spec, shell="powershell"),
        )
        print_curl(
            "ProxyClient.request_to_curl cmd 单行",
            client.request_to_curl(spec, shell="cmd"),
        )
        print_curl(
            "ProxyClient.request_to_curl 脱敏版本（masked=True）",
            client.request_to_curl(spec, shell="bash", masked=True),
        )

        if do_real_request:
            print("[Curl示例] 开始真实发起请求验证导出 curl 与实际请求一致")
            response = await client.request(spec, return_exceptions=True)
            if response.error is not None:
                print(
                    f"[Curl示例] 真实请求失败 - 状态: {response.status} 代理: {response.proxy_snapshot} "
                    f"错误类型: {type(response.error).__name__} 错误: {response.error}"
                )
            else:
                body = response.text()
                if len(body) > 500:
                    body = body[:500] + "...[已截断]"
                print(
                    f"[Curl示例] 真实请求成功 - 状态: {response.status} 耗时: {response.elapsed_ms:.2f}ms "
                    f"最终URL: {response.final_url} 代理: {response.proxy_snapshot}"
                )
                print(f"[Curl示例] 响应正文预览 - body: {body}")
            response.close()
        else:
            print("[Curl示例] 跳过真实请求 - IPWEB_CURL_DEMO_REAL=0")

    print("[Curl示例] 输出完成")


if __name__ == "__main__":
    asyncio.run(main())
