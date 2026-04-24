import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from proxy_scheduler import DynamicProxyGenerator


def main() -> None:
    """
    演示动态代理生成器读取系统环境和项目 .env 的基础调用方式。

    Args:
        无。

    Returns:
        None: 无返回值。

    Raises:
        RuntimeError: 缺少必要环境变量时抛出。
    """

    # =========================
    # 1. 加载项目 .env 配置
    # 2. 读取系统环境变量
    # 3. 创建动态代理生成器
    # 4. 查询地区代码
    # 5. 生成单条代理
    # 6. 输出脱敏结果
    # =========================
    env_path = ROOT / ".env"
    if env_path.exists():
        print(f"[生成器示例] 读取项目环境文件 - path: {env_path}")
        for line in env_path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text or text.startswith("#") or "=" not in text:
                continue
            key, value = text.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    else:
        print(f"[生成器示例] 未找到项目环境文件 - path: {env_path}")

    user_id = os.environ.get("IPWEB_USER_ID", "").strip()
    password = os.environ.get("IPWEB_PASSWORD", "").strip()
    gateway = os.environ.get("IPWEB_GATEWAY", "global").strip()
    country_code = os.environ.get("IPWEB_COUNTRY_CODE", "US").strip()
    state_code = os.environ.get("IPWEB_STATE_CODE", "").strip()
    city_code = os.environ.get("IPWEB_CITY_CODE", "").strip()
    protocol = os.environ.get("IPWEB_PROTOCOL", "http").strip()
    duration_minutes = int(os.environ.get("IPWEB_DURATION_MINUTES", "5").strip())

    print("[生成器示例] 读取系统环境完成")
    print(f"[生成器示例] 环境参数 - gateway: {gateway} country_code: {country_code} protocol: {protocol}")

    if not user_id or not password:
        raise RuntimeError("请先设置 IPWEB_USER_ID 和 IPWEB_PASSWORD 环境变量")

    print("[生成器示例] 开始创建动态代理生成器")
    generator = DynamicProxyGenerator(
        user_id=user_id,
        password=password,
        gateway=gateway,
    )

    print(f"[生成器示例] 查询地区代码 - country_code: {country_code}")
    if country_code != "000":
        states = generator.list_states(country_code)
        print(f"[生成器示例] 查询完成 - state_count: {len(states)}")
    else:
        print("[生成器示例] 跳过地区查询 - country_code: 000")

    print(f"[生成器示例] 开始生成代理 - country_code: {country_code}")
    proxy = generator.generate(
        count=1,
        country_code=country_code,
        state_code=state_code,
        city_code=city_code,
        duration_minutes=duration_minutes,
        protocol=protocol,
    )
    print(f"[生成器示例] 生成完成 - proxy_url: {proxy.safe_proxy_url}")
    print(f"[生成器示例] 生成完成 - http_url: {proxy.safe_proxies['http']}")
    print(f"[生成器示例] 生成完成 - https_url: {proxy.safe_proxies['https']}")
    print(f"[生成器示例] 生成完成 - socks5_url: {proxy.safe_proxies['socks5']}")
    print(f"[生成器示例] 生成完成 - socks5h_url: {proxy.safe_proxies['socks5h']}")
    print(f"[生成器示例] 代理主机 - host: {proxy.host}")
    print(f"[生成器示例] 代理端口 - port: {proxy.port}")
    print(f"[生成器示例] 代理用户 - user: {proxy.masked_user}")
    print(f"[生成器示例] 代理密码 - password: {proxy.masked_password}")
    print(f"[生成器示例] 代理协议 - protocol: {proxy.protocol}")
    print(f"[生成器示例] 字典导出 - data: {proxy.to_dict(masked=True)}")
    print(f"[生成器示例] 环境变量导出 - env: {proxy.to_env(masked=True)}")

if __name__ == "__main__":
    main()
