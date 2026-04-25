import asyncio
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from proxy_scheduler import DynamicProxyGenerator
from proxy_scheduler_client import Limits, ProxyClient


REAL_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
}


def load_env() -> None:
    """
    读取项目根目录下的 .env 文件并写入进程环境变量。

    Returns:
        None: 无返回值。
    """

    env_path = ROOT / ".env"
    if not env_path.exists():
        print(f"[真实网站示例] 未找到项目环境文件 - path: {env_path}")
        return
    print(f"[真实网站示例] 读取项目环境文件 - path: {env_path}")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


async def main() -> None:
    """
    生成动态代理并带上目标站真实请求头抓取指定页面。

    Returns:
        None: 无返回值。

    Raises:
        RuntimeError: 缺少必要环境变量时抛出。
    """

    # =========================
    # 1. 加载项目 .env 配置
    # 2. 读取代理生成与请求参数
    # 3. 生成单条动态代理
    # 4. 构建客户端并注入真实请求头
    # 5. 发起 GET 请求并打印响应摘要
    # =========================
    load_env()

    user_id = os.environ.get("IPWEB_USER_ID", "").strip()
    password = os.environ.get("IPWEB_PASSWORD", "").strip()
    gateway = os.environ.get("IPWEB_GATEWAY", "global").strip()
    country_code = os.environ.get("IPWEB_COUNTRY_CODE", "US").strip()
    state_code = os.environ.get("IPWEB_STATE_CODE", "").strip()
    city_code = os.environ.get("IPWEB_CITY_CODE", "").strip()
    protocol = os.environ.get("IPWEB_PROTOCOL", "http").strip()
    duration_minutes = int(os.environ.get("IPWEB_DURATION_MINUTES", "5").strip())
    target_url = os.environ.get("IPWEB_TEST_URL", "").strip()
    timeout = float(os.environ.get("IPWEB_SITE_TIMEOUT", "30").strip())
    verify = os.environ.get("IPWEB_VERIFY", "true").strip().lower() not in {"0", "false", "no"}

    if not user_id or not password:
        raise RuntimeError("请先设置 IPWEB_USER_ID 和 IPWEB_PASSWORD 环境变量")

    print(
        f"[真实网站示例] 请求参数 - URL: {target_url} gateway: {gateway} "
        f"country_code: {country_code} protocol: {protocol} timeout: {timeout} verify: {verify}"
    )

    print("[真实网站示例] 开始创建动态代理生成器")
    generator = DynamicProxyGenerator(
        user_id=user_id,
        password=password,
        gateway=gateway,
    )

    print(
        f"[真实网站示例] 开始生成代理 - country_code: {country_code} "
        f"state_code: {state_code or '-'} city_code: {city_code or '-'} protocol: {protocol}"
    )
    proxy = generator.generate(
        country_code=country_code,
        state_code=state_code,
        city_code=city_code,
        duration_minutes=duration_minutes,
        protocol=protocol,
    )
    print(
        f"[真实网站示例] 代理生成完成 - session_id: {proxy.session_id} "
        f"proxy: {proxy.safe_proxy_url} host: {proxy.host} port: {proxy.port}"
    )

    limits = Limits(
        concurrency=1,
        connector_limit=1,
        connector_limit_per_host=0,
        connect_timeout=min(timeout, 30.0),
        read_timeout=timeout,
        total_timeout=timeout,
    )

    print(
        f"[真实网站示例] 初始化代理客户端 - proxy: {proxy.safe_proxy_url} "
        f"timeout: {timeout} verify: {verify}"
    )
    async with ProxyClient(
        proxy_url=proxy.proxy_url,
        limits=limits,
        default_headers=REAL_HEADERS,
        user_agent=REAL_HEADERS["User-Agent"],
        verbose=True,
    ) as client:
        print(f"[真实网站示例] 开始请求 - URL: {target_url} 方法: GET")
        response = await client.request(
            "GET",
            target_url,
            timeout=timeout,
            tag="real-site",
            meta={"verify": verify, "allow_redirects": True},
            return_exceptions=True,
        )
        if response.error is not None:
            print(
                f"[真实网站示例] 请求失败 - URL: {response.url} 状态: {response.status} "
                f"代理: {response.proxy_snapshot} "
                f"错误类型: {type(response.error).__name__} 错误: {response.error}"
            )
            response.close()
            return

        body = response.text()
        # if len(body) > 800:
        #     body = body[:800] + "...[已截断]"

        print(
            f"[真实网站示例] 请求成功 - URL: {response.final_url} 状态: {response.status} "
            f"耗时: {response.elapsed_ms:.2f}ms 代理: {response.proxy_snapshot}"
        )
        print(f"[真实网站示例] 响应编码 - encoding: {response.encoding}")
        print(
            f"[真实网站示例] 响应头摘要 - content-type: {response.headers.get('content-type')} "
            f"server: {response.headers.get('server')} "
            f"content-length: {response.headers.get('content-length')}"
        )
        print(f"[真实网站示例] 响应正文预览 - body: {body}")
        print(f"[真实网站示例] 客户端指标快照 - metrics: {client.metrics.snapshot()}")
        response.close()


if __name__ == "__main__":
    asyncio.run(main())
