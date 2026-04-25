# ipweb-proxy-sdk

IPWEB 动态代理 SDK。

核心能力是动态代理地址生成；可选能力是基于用户传入代理地址的异步请求客户端。请求客户端与代理生成器完全解耦，客户端只接收 `proxy_url` 字符串，代理来源可以是本 SDK 生成器，也可以是用户自己的代理服务。

## 功能范围

- 支持单条代理生成。
- 支持批量代理生成。
- 支持同一入口下的小批量列表返回和大批量流式返回。
- 支持迭代式批量生成，适合大批量低内存场景。
- 支持国家、州、城市代码校验。
- 支持国家、州、城市代码查询。
- 支持 `http`、`socks5`、`socks5h` 代理地址生成。
- 兼容 `socket5`、`socket5h` 写法，会自动规范化为 `socks5`、`socks5h`。
- 支持 32 位十六进制 `session_id` 固定会话。
- 支持脱敏输出、字典导出、JSON 导出、环境变量导出。
- 可选异步请求客户端支持 `http`、`https`、`socks5`、`socks5h` 代理。
- 可选异步请求客户端支持会话状态导入导出、背压流式请求、单进程多客户端集群和多进程运行器。

## 安装

本地开发依赖：

```bash
pip install -r requirements.txt
```

可选异步请求层依赖：

```bash
pip install ipweb-proxy-sdk[client]
```

SDK 使用入口：

```python
from proxy_scheduler import DynamicProxyGenerator
```

可选异步请求层入口：

```python
from proxy_scheduler_client import ProxyClient, RequestSpec
```

项目本地测试可以使用根目录 `.env`，也可以直接设置系统环境变量；系统环境变量优先级更高。

```text
IPWEB_USER_ID=B_XXXXX
IPWEB_PASSWORD=YOUR_PASSWORD
IPWEB_GATEWAY=global
IPWEB_COUNTRY_CODE=US
IPWEB_PROTOCOL=http
IPWEB_DURATION_MINUTES=5
```

## 快速开始

```python
from proxy_scheduler import DynamicProxyGenerator


def main() -> None:
    """
    动态代理生成示例。

    Returns:
        None: 无返回值。
    """

    print("[生成器示例] 开始创建动态代理生成器")
    generator = DynamicProxyGenerator(
        user_id="YOU_USER_ID",
        password="YOU_USER_PASSWORD",
        gateway="apac",
    )

    print("[生成器示例] 开始生成代理 - country_code: US protocol: http")
    proxy = generator.generate(
        country_code="US",
        duration_minutes=5,
        protocol="http",
    )

    print(f"[生成器示例] 生成完成 - proxy_url: {proxy.safe_proxy_url}")
    print(f"[生成器示例] 代理主机 - host: {proxy.host}")
    print(f"[生成器示例] 代理端口 - port: {proxy.port}")
    print(f"[生成器示例] 代理用户 - user: {proxy.masked_user}")
    print(f"[生成器示例] 代理密码 - password: {proxy.masked_password}")
    print(f"[生成器示例] 代理协议 - protocol: {proxy.protocol}")


if __name__ == "__main__":
    main()
```

## 创建生成器

```python
generator = DynamicProxyGenerator(
    user_id="YOU_USER_ID",
    password="YOU_USER_PASSWORD",
    gateway="apac",
)
```

参数说明：

- `user_id`：IPWEB 代理账号用户标识，必填。
- `password`：IPWEB 代理账号密码，必填。
- `gateway`：官方代理网关别名，默认 `apac`。

支持的网关别名：

- `us` / `americas` / `america` / `global`：映射到 `gate1.ipweb.cc:7778`。
- `apac` / `asia`：映射到 `gate2.ipweb.cc:7778`。
- `emea` / `europe`：映射到 `gate3.ipweb.cc:7778`。

也可以直接传入官方地址：`gate1.ipweb.cc:7778`、`gate2.ipweb.cc:7778`、`gate3.ipweb.cc:7778`。

SDK 不支持自定义网关；传入非官方别名或非官方地址会抛出 `ValueError`。

## 生成代理

`generate()` 是统一生成入口。

```python
proxy = generator.generate(country_code="US")
proxies = generator.generate(count=10, country_code="US")
stream = generator.generate(count=1_000_000, country_code="US")
empty = generator.generate(count=0)
```

返回规则：

- `count=1` 返回 `PreparedProxy`。
- `1<count<=100000` 返回 `list[PreparedProxy]`。
- `count>100000` 返回 `Iterator[PreparedProxy]`，适合大批量低内存场景。
- `count=0` 返回空列表。
- `count>1` 时不能传入 `session_id`。
- 单次批量调用内生成的 `session_id` 和 `proxy_url` 保证本地全局唯一。

参数说明：

- `count`：生成数量，默认 `1`，最大 `10000000`。
- `country_code`：国家代码，默认 `"000"`，表示不限制国家。
- `duration_minutes`：会话时长，默认 `5`，允许范围 `1` 到 `1440`。
- `session_id`：自定义会话标识，仅单条生成可用，必须是 32 位十六进制字符串。
- `state_code`：州代码，必须属于指定国家。
- `city_code`：城市代码，必须属于指定国家；同时传州代码时城市必须属于该州。
- `protocol`：主代理协议。

## 协议说明

支持协议：

- `http`
- `socks5`
- `socks5h`
- `socket5`
- `socket5h`

兼容说明：

- `socket5` 会自动规范化为 `socks5`。
- `socket5h` 会自动规范化为 `socks5h`。
- `https` 兼容旧版本写法，但返回的是 HTTP CONNECT 代理地址，不代表代理网关本身是 HTTPS 代理服务。
- 无论主协议是什么，返回对象都会保留 `http`、`https`、`socks5`、`socks5h` 四种地址。

## PreparedProxy

单条生成返回 `PreparedProxy`。

常用字段：

- `proxy.proxy_url`：当前主协议对应的完整代理地址。
- `proxy.safe_proxy_url`：脱敏后的当前主代理地址。
- `proxy.proxies`：完整多协议代理地址映射。
- `proxy.safe_proxies`：脱敏后的多协议代理地址映射。
- `proxy.username`：最终拼接后的代理认证用户名。
- `proxy.gateway`：实际使用的网关，格式为 `host:port`。
- `proxy.host`：代理网关主机。
- `proxy.port`：代理网关端口。
- `proxy.user`：代理认证用户名，等同于 `proxy.username`。
- `proxy.masked_user`：脱敏后的代理认证用户名。
- `proxy.password`：代理认证密码。
- `proxy.masked_password`：脱敏后的代理认证密码。
- `proxy.protocol`：当前主代理协议。
- `proxy.session_id`：当前代理会话标识。
- `proxy.country_code`：当前国家代码。
- `proxy.state_code`：当前州代码。
- `proxy.city_code`：当前城市代码。
- `proxy.duration_minutes`：当前会话时长。

常用属性：

```python
print(proxy.http_url)
print(proxy.https_url)
print(proxy.socks5_url)
print(proxy.socks5h_url)
```

按协议取地址：

```python
print(proxy.url_for("http"))
print(proxy.url_for("socks5"))
print(proxy.url_for("socket5"))
```

## 脱敏与导出

默认建议日志中使用脱敏字段。

```python
print(proxy.safe_proxy_url)
print(proxy.masked_user)
print(proxy.masked_password)
print(proxy.to_dict(masked=True))
print(proxy.to_json(masked=True))
print(proxy.explain(masked=True))
```

需要给外部程序注入环境变量时可以导出真实代理地址：

```python
env = proxy.to_env(masked=False)
print(env["HTTP_PROXY"])
print(env["HTTPS_PROXY"])
print(env["ALL_PROXY"])
```

## 批量生成

一次性返回列表：

```python
proxies = generator.generate(
    count=10,
    country_code="US",
    duration_minutes=5,
    protocol="http",
)

for item in proxies:
    print(item.safe_proxy_url)
```

兼容旧版本的批量方法：

```python
proxies = generator.generate_many(
    10,
    country_code="US",
    duration_minutes=5,
    protocol="http",
)
```

`generate_many()` 保持旧版“完整列表返回”的语义；如果数量超过 `100000`，会直接抛错，避免把超大结果重新全部放进内存。大批量场景请继续使用同一个 `generate(count=...)` 入口。

大批量低内存生成：

```python
for proxy in generator.iter_generate(count=1000, country_code="US", protocol="http"):
    print(proxy.safe_proxy_url)
```

同一个统一入口在超大数量时也会自动切换成流式返回：

```python
stream = generator.generate(
    count=10_000_000,
    country_code="US",
    duration_minutes=5,
    protocol="http",
)

for proxy in stream:
    print(proxy.safe_proxy_url)
```

说明：

- `generate(count=10_000_000)` 不会一次性创建一千万个 `PreparedProxy` 列表。
- SDK 会在单次调用内按顺序生成全局唯一的 32 位十六进制 `session_id`。
- 这里保证的是 SDK 本地生成结果不重复，不保证最终出口 IP 一定不重复。

## 地区代码查询

查询国家：

```python
countries = generator.list_countries()
print(countries)
```

查询州：

```python
states = generator.list_states("US")
print(states)
```

查询城市：

```python
cities = generator.list_cities("US")
print(cities)

state_cities = generator.list_cities("US", state_code="2079")
print(state_cities)
```

## 指定地区生成

指定国家：

```python
proxy = generator.generate(
    country_code="US",
    duration_minutes=10,
    protocol="http",
)
```

指定国家、州、城市：

```python
proxy = generator.generate(
    country_code="US",
    state_code="2079",
    city_code="75544",
    duration_minutes=5,
    protocol="socks5",
)
```

指定固定 `session_id`：

```python
proxy = generator.generate(
    country_code="US",
    duration_minutes=15,
    session_id="1234567890abcdef1234567890abcdef",
    protocol="http",
)
```

## 参数校验

SDK 会在生成前执行参数校验：

- `user_id` 不能为空，只支持字母、数字、下划线、点、短横线。
- `password` 不能为空。
- `gateway` 必须是官方支持的网关别名或官方 `gate*.ipweb.cc:7778` 地址。
- `count` 必须是整数，范围 `0` 到 `10000000`。
- `duration_minutes` 必须是整数，范围 `1` 到 `1440`。
- `session_id` 必须是 32 位十六进制字符串。
- `country_code` 必须是 `000` 或两位国家代码。
- `state_code` 必须属于指定国家。
- `city_code` 必须属于指定国家。
- 同时传入 `state_code` 和 `city_code` 时，城市必须属于该州。

## 可选异步请求客户端

请求客户端不是代理生成器的一部分，只有显式安装 `ipweb-proxy-sdk[client]` 并导入 `proxy_scheduler_client` 时才使用。客户端不自动生成代理、不维护代理池、不做代理评分，也不主动检测代理可用性。

安装基础异步请求能力：

```bash
pip install ipweb-proxy-sdk[client]
```

如果需要 SOCKS 代理：

```bash
pip install ipweb-proxy-sdk[socks]
```

如果需要全部可选能力：

```bash
pip install ipweb-proxy-sdk[all]
```

客户端核心对象：

- `ProxyClient`：单代理、单会话异步客户端。
- `RequestSpec`：一次请求的纯数据规格。
- `Response`：完全解耦 aiohttp 的响应对象。
- `SessionState`：Cookie、sticky headers、local_storage、DNS/TLS 快照预留字段。
- `Limits`：并发、连接池、超时、背压队列和响应落盘阈值。
- `ClientCluster`：单进程多 `ProxyClient` 调度。
- `ProcessPoolRunner`：多进程请求运行器。

生产环境建议保持 `verbose=False`。`verbose=True` 会通过 `logging` 输出逐请求中文调试日志，适合排查问题，不适合百万级吞吐压测。

调试时可以导出 curl 命令：

```python
spec = RequestSpec(
    method="POST",
    url="https://example.com/api",
    headers={"x-trace-id": "demo"},
    json={"name": "alice"},
    meta={"verify": False},
)

print(spec.to_curl(masked=False, shell="bash"))
print(client.request_to_curl("GET", "https://example.com/profile", masked=True, shell="cmd"))
```

说明：

- `RequestSpec.to_curl()` 导出的是“请求规格视角”的 curl。
- `ProxyClient.request_to_curl()` 会合并代理地址、默认头、sticky headers 和 Cookie，导出更接近实际发送态的 curl。
- 默认 `masked=False`，会优先导出可直接执行的复现命令。
- 需要安全写日志时，显式传 `masked=True`。
- `shell` 支持 `auto`、`bash`、`powershell` 和 `cmd`；`auto` 会在 Windows 下默认生成 `cmd` 风格命令，其他平台默认生成 `bash` 风格命令。
- 在 `cmd.exe` 中直接粘贴执行时，请显式使用 `shell="cmd"`；在 PowerShell 中请使用 `shell="powershell"`。

单客户端示例：

```python
import asyncio

from proxy_scheduler import DynamicProxyGenerator
from proxy_scheduler_client import Limits, ProxyClient


async def main() -> None:
    """
    异步代理请求调用示例。

    Returns:
        None: 无返回值。
    """

    # =========================
    # 1. 生成代理
    # 2. 创建客户端
    # 3. 发起请求
    # 4. 导出会话状态
    # 5. 输出结果
    # 6. 关闭资源
    # =========================
    generator = DynamicProxyGenerator(
        user_id="YOU_USER_ID",
        password="YOU_USER_PASSWORD",
        gateway="global",
    )
    proxy = generator.generate(country_code="US", protocol="http")

    async with ProxyClient(
        proxy_url=proxy.proxy_url,
        limits=Limits(concurrency=100, connector_limit=20),
        verbose=True,
    ) as client:
        client.sticky_header("x-session-hint", proxy.session_state_hint())
        response = await client.get(
            "https://api.ipify.org?format=json",
            headers={"accept": "application/json"},
            timeout=30,
            return_exceptions=True,
        )
        state = client.export_state()

    print(response.status)
    print(response.text())
    print(state.proxy_hint)


if __name__ == "__main__":
    asyncio.run(main())
```

批量并发请求建议使用 `stream()`，内部使用固定 pending 窗口做背压，不会一次性把百万级 `RequestSpec` 灌入内存。`stream()` 与同一个客户端上的 `get/post/request()` 共享 `Limits.concurrency` 并发上限；压测或生产批量任务期间建议只使用 `stream()`，不要在同一个 `ProxyClient` 上同时直接发起额外请求：

```python
requests = [
    RequestSpec(method="GET", url="https://example.com", tag=f"task-{index}")
    for index in range(1000)
]

async with ProxyClient(proxy_url=proxy.proxy_url, limits=Limits(concurrency=500)) as client:
    async for response in client.stream(requests, return_exceptions=True):
        print(response.request_tag, response.status, response.ok)
```

单进程多代理：

```python
from proxy_scheduler_client import ClientCluster, ProxyClient

proxies = generator.generate(count=3, country_code="US", protocol="http")
clients = [ProxyClient(proxy_url=item.proxy_url) for item in proxies]

async with ClientCluster(clients) as cluster:
    responses = await cluster.gather(requests)
```

`ClientCluster.stream()` 会按每个 `ProxyClient` 的 `Limits.concurrency` 分片控制窗口，避免单个客户端被集群总窗口压爆。流式模式优先保证背压和吞吐，不在任务内部做跨客户端失败重试；需要严格重试语义时使用 `ClientCluster.request()`，或者在 `stream()/gather()` 返回失败响应后自行补偿。`FailurePolicy.SKIP` 表示本次只尝试当前路由命中的一个客户端，不继续切到下一个；`FailurePolicy.RETRY_ON_NEXT` 才会继续尝试后续客户端。

多进程运行器要求 `worker_factory` 是可 pickle 的顶层函数，子进程内自行构造 `ProxyClient` 或 `ClientCluster`，避免连接池跨进程迁移：

```python
from proxy_scheduler_client import ProcessPoolRunner, ProxyClient


def build_worker():
    """
    构造子进程客户端。

    Returns:
        ProxyClient: 子进程客户端。
    """

    return ProxyClient(proxy_url="http://user:password@gate1.ipweb.cc:7778")


async with ProcessPoolRunner(build_worker, process_count=4) as runner:
    responses = await runner.gather(requests)
```

`ProcessPoolRunner` 内部会对并发 `stream()/gather()` 调用做串行化，避免不同批次混用同一组子进程队列。若某个 worker 异常退出，运行器会重启该 worker 并重投受影响请求；但重启后的 worker 会重新执行 `worker_factory()`，因此 worker 内部未导出的登录态、Cookie 和本地会话状态不会自动继承，生产场景应让 `worker_factory()` 能幂等恢复所需状态。

## 发布范围

构建包只包含：

```text
proxy_scheduler/
proxy_scheduler/data/geo_codes.min.json
```

运行时使用内置 `proxy_scheduler/data/geo_codes.min.json`；根目录的 `geo_codes.xlsx` 仅作为开发阶段生成快照的数据源，不建议上传到 PyPI 包中。代理池、代理评分和代理可用性检测不属于当前 SDK 发布范围。
