import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from proxy_scheduler import DynamicProxyGenerator


def main() -> None:
    """
    演示使用同一个生成器入口流式输出一百万条代理地址到文本文件。

    Args:
        无。

    Returns:
        None: 无返回值。

    Raises:
        RuntimeError: 缺少必要环境变量或生成结果不符合预期时抛出。
    """

    # =========================
    # 1. 加载项目 .env 配置
    # 2. 读取系统环境变量
    # 3. 创建动态代理生成器
    # 4. 通过统一入口触发百万级流式生成
    # 5. 逐行输出真实代理到文本文件
    # 6. 输出进度和最终结果
    # =========================
    env_path = ROOT / ".env"
    if env_path.exists():
        print(f"[百万示例] 读取项目环境文件 - path: {env_path}")
        for line in env_path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text or text.startswith("#") or "=" not in text:
                continue
            key, value = text.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    else:
        print(f"[百万示例] 未找到项目环境文件 - path: {env_path}")

    user_id = os.environ.get("IPWEB_USER_ID", "").strip()
    password = os.environ.get("IPWEB_PASSWORD", "").strip()
    gateway = os.environ.get("IPWEB_GATEWAY", "global").strip()
    country_code = os.environ.get("IPWEB_COUNTRY_CODE", "US").strip()
    state_code = os.environ.get("IPWEB_STATE_CODE", "").strip()
    city_code = os.environ.get("IPWEB_CITY_CODE", "").strip()
    protocol = os.environ.get("IPWEB_PROTOCOL", "http").strip()
    duration_minutes = int(os.environ.get("IPWEB_DURATION_MINUTES", "5").strip())
    output_path = Path(
        os.environ.get(
            "IPWEB_MILLION_OUTPUT_PATH",
            str(ROOT / "examples" / "generator" / "million_proxies.txt"),
        ).strip()
    )
    total_count = 1_000_000
    progress_step = 10_000

    print("[百万示例] 读取系统环境完成")
    print(
        f"[百万示例] 请求参数 - gateway: {gateway} country_code: {country_code} "
        f"protocol: {protocol} duration: {duration_minutes} total: {total_count} "
        f"output: {output_path}"
    )

    if not user_id or not password:
        raise RuntimeError("请先设置 IPWEB_USER_ID 和 IPWEB_PASSWORD 环境变量")

    print("[百万示例] 开始创建动态代理生成器")
    generator = DynamicProxyGenerator(
        user_id=user_id,
        password=password,
        gateway=gateway,
    )

    print("[百万示例] 开始触发统一入口生成 - mode: stream count: 1000000")
    stream = generator.generate(
        count=total_count,
        country_code=country_code,
        state_code=state_code,
        city_code=city_code,
        duration_minutes=duration_minutes,
        protocol=protocol,
    )
    if isinstance(stream, list) or not hasattr(stream, "__iter__"):
        raise RuntimeError("百万级生成未进入流式模式，请检查生成器实现")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    written_count = 0
    first_proxy = ""
    last_proxy = ""

    with output_path.open("w", encoding="utf-8", newline="\n") as output_file:
        for proxy in stream:
            if written_count == 0:
                first_proxy = proxy.safe_proxy_url
            last_proxy = proxy.safe_proxy_url
            output_file.write(proxy.proxy_url)
            output_file.write("\n")
            written_count += 1

            if written_count % progress_step == 0:
                print(
                    f"[百万示例] 生成进度 - current: {written_count}/{total_count} "
                    f"sample_first: {first_proxy} sample_last: {last_proxy}"
                )

    if written_count != total_count:
        raise RuntimeError(f"生成数量不符合预期: expected={total_count} actual={written_count}")

    print(
        f"[百万示例] 输出完成 - total: {written_count} output: {output_path} "
        f"sample_first: {first_proxy} sample_last: {last_proxy}"
    )


if __name__ == "__main__":
    main()
