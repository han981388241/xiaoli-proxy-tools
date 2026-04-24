import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from proxy_scheduler import DynamicProxyGenerator


def main() -> None:
    """
    演示动态代理生成器的基础调用方式。

    Returns:
        None: 无返回值。
    """

    # =========================
    # 1. 构建生成器参数
    # 2. 创建动态代理生成器
    # 3. 生成单条代理
    # 4. 输出结果
    # =========================
    print("[生成器示例] 开始创建动态代理生成器")
    generator = DynamicProxyGenerator(
        user_id="YOU_USER_ID",
        password="YOU_USER_PASSWORD",
        gateway="global",
    )

    print("[生成器示例] 开始生成代理 - country_code: US")
    proxy = generator.generate(
        count=1,  # 自定义返回数量
        country_code="US",
        # state_code="2079",
        # city_code="75544",
        # protocol="socks5",
    )

    print(f"[生成器示例] 生成完成 - proxy_url: {proxy.proxy_url}")
    print(f"[生成器示例] 生成完成 - http_url: {proxy.http_url}")
    print(f"[生成器示例] 生成完成 - https_url: {proxy.https_url}")
    print(f"[生成器示例] 生成完成 - socks5_url: {proxy.socks5_url}")
    print(f"[生成器示例] 生成完成 - socks5h_url: {proxy.socks5h_url}")
    print(f"[生成器示例] 代理主机 - host: {proxy.host}")
    print(f"[生成器示例] 代理端口 - port: {proxy.port}")
    print(f"[生成器示例] 代理用户 - user: {proxy.user}")
    print(f"[生成器示例] 代理密码 - password: {proxy.password}")
    print(f"[生成器示例] 代理协议 - protocol: {proxy.protocol}")


if __name__ == "__main__":
    main()
