# ipweb-proxy-sdk 0.1.2

`ipweb-proxy-sdk` 是一套面向 IPWEB 动态代理场景的 Python SDK。

当前版本 `0.1.2` 的定位分成两层：

- `proxy_scheduler`：只负责动态代理地址生成、参数校验、地区代码查询、批量与流式输出。
- `proxy_scheduler_client`：只负责基于用户传入代理地址发起异步请求，支持单客户端、集群和多进程运行。

两层能力完全解耦：

- 生成器不发请求、不维护代理池、不做代理评分。
- 请求客户端不负责生成代理，只消费 `proxy_url` 字符串。

这意味着你既可以：

- 用 `proxy_scheduler` 生成 IPWEB 代理地址；
- 再把这些地址交给 `proxy_scheduler_client`；
- 也可以完全跳过生成器，直接把你自己的代理地址传给客户端。

## 功能总览

### 代理生成器 `proxy_scheduler`

- 支持单条代理生成。
- 支持批量代理生成。
- 支持同一入口下的小批量列表返回和大批量流式返回。
- 支持最大 `10_000_000` 条的单次流式生成。
- 支持批量场景下本地唯一的 `session_id` 和代理链接生成。
- 支持 `http`、`https`、`socks5`、`socks5h` 四种代理地址导出。
- 兼容 `socket5`、`socket5h` 写法，自动规范化为 `socks5`、`socks5h`。
- 支持国家、州、城市代码校验。
- 支持国家、州、城市查询。
- 支持查询时返回名称信息：
  - 国家返回中文名和英文名；
  - 州、城市返回源数据中的英文/原始名称。
- 支持脱敏输出、字典导出、JSON 导出、环境变量导出。
- 支持单条自定义 `session_id`，以及批量自定义 `session_id` 生成函数。

### 异步请求客户端 `proxy_scheduler_client`

- 支持 `http`、`https`、`socks5`、`socks5h` 代理请求。
- 支持 `socket5`、`socket5h` 代理协议别名。
- 支持单客户端请求。
- 支持 `GET / POST / PUT / DELETE / PATCH / HEAD / OPTIONS` 快捷方法。
- 支持 `RequestSpec` 纯数据请求规格。
- 支持默认请求头、会话级请求头、Cookie、会话状态导入导出。
- 支持 `stream()` 背压流式请求。
- 支持 `ClientCluster` 单进程多代理调度。
- 支持 `ProcessPoolRunner` 多进程运行。
- 支持将请求导出为 curl 命令。
- 支持 `bash`、`cmd`、`powershell` 三种 curl 输出风格。
- 支持中文指标快照，包含成功率、429 数量、成功请求均值、热点延迟区间、状态分布和错误分布。

## 安装

基础安装：

```bash
pip install ipweb-proxy-sdk==0.1.2(未发布)
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple ipweb-proxy-sdk==0.1.2
```

如果需要异步请求客户端：

```bash
pip install "ipweb-proxy-sdk[client]==0.1.2"
```

如果需要 SOCKS：

```bash
pip install "ipweb-proxy-sdk[socks]==0.1.2"
```

全部可选能力：

```bash
pip install "ipweb-proxy-sdk[all]==0.1.2"
```

本地开发依赖：

```bash
pip install -r requirements.txt
```

## 导入路径

生成器入口：

```python
from proxy_scheduler import DynamicProxyGenerator
```

请求客户端入口：

```python
from proxy_scheduler_client import ProxyClient, ClientCluster, ProcessPoolRunner, Limits, RequestSpec
```

更细的模型入口：

```python
from proxy_scheduler_client.response import Response, Headers
from proxy_scheduler_client.session import CookieRecord, SessionState
from proxy_scheduler_client.transport import Transport, AiohttpTransport
```

## 环境变量

项目本地测试可以直接使用根目录 `.env`，也可以使用系统环境变量。
系统环境变量优先级更高。

```text
IPWEB_USER_ID=B_XXXXX
IPWEB_PASSWORD=YOUR_PASSWORD
IPWEB_GATEWAY=global
IPWEB_COUNTRY_CODE=US
IPWEB_STATE_CODE=
IPWEB_CITY_CODE=
IPWEB_PROTOCOL=http
IPWEB_DURATION_MINUTES=5
IPWEB_TEST_URL=https://api.ipify.org?format=json
```

## 快速开始

### 只生成代理

```python
from proxy_scheduler import DynamicProxyGenerator


def main() -> None:
    """
    动态代理生成示例。

    Returns:
        None: 无返回值。
    """

    generator = DynamicProxyGenerator(
        user_id="YOU_USER_ID",
        password="YOU_USER_PASSWORD",
        gateway="global",
    )

    proxy = generator.generate(
        country_code="US",
        duration_minutes=5,
        protocol="http",
    )

    print(proxy.safe_proxy_url)
    print(proxy.host, proxy.port)
    print(proxy.masked_user, proxy.masked_password)


if __name__ == "__main__":
    main()
```

### 生成代理后发请求

```python
import asyncio

from proxy_scheduler import DynamicProxyGenerator
from proxy_scheduler_client import Limits, ProxyClient


async def main() -> None:
    """
    生成代理并发起异步请求。

    Returns:
        None: 无返回值。
    """

    generator = DynamicProxyGenerator(
        user_id="YOU_USER_ID",
        password="YOU_USER_PASSWORD",
        gateway="global",
    )
    proxy = generator.generate(country_code="US", protocol="http")

    async with ProxyClient(
        proxy_url=proxy.proxy_url,
        limits=Limits(concurrency=10, connector_limit=10),
        verbose=True,
    ) as client:
        response = await client.get(
            "https://api.ipify.org?format=json",
            timeout=30,
            return_exceptions=True,
        )
        print(response.status)
        print(response.text())
        print(client.metrics.snapshot())


if __name__ == "__main__":
    asyncio.run(main())
```

## 代理生成器详解

### 创建生成器

```python
generator = DynamicProxyGenerator(
    user_id="YOU_USER_ID",
    password="YOU_USER_PASSWORD",
    gateway="apac",
)
```

参数说明：

- `user_id`：IPWEB 账号用户标识，必填。
- `password`：IPWEB 账号密码，必填。
- `gateway`：官方网关别名或官方地址，默认 `apac`。

支持的网关别名：

- `us` / `america` / `americas` / `global` -> `gate1.ipweb.cc:7778`
- `apac` / `asia` -> `gate2.ipweb.cc:7778`
- `emea` / `europe` -> `gate3.ipweb.cc:7778`

也支持直接传入官方地址：

- `gate1.ipweb.cc:7778`
- `gate2.ipweb.cc:7778`
- `gate3.ipweb.cc:7778`

当前 SDK 不支持自定义第三方网关地址。
如果 `gateway` 带 path、query、fragment，或不在官方支持范围内，会抛出 `ValueError`。

### generate() 统一入口

`generate()` 是当前版本的统一入口。

```python
proxy = generator.generate(country_code="US")
proxies = generator.generate(count=10, country_code="US")
stream = generator.generate(count=1_000_000, country_code="US")
empty = generator.generate(count=0)
```

返回规则：

- `count=0`：返回空列表 `[]`
- `count=1`：返回单个 `PreparedProxy`
- `1 < count <= 100000`：返回 `list[PreparedProxy]`
- `count > 100000`：返回 `Iterator[PreparedProxy]`

也就是说：

- 小批量更适合直接拿列表；
- 大批量会自动切换到流式模式，避免一次性创建超大列表。

### 流式输出限制

当前流式输出的主要限制是：

- 单次最大数量 `10_000_000`
- 是同步迭代器，不是异步迭代器
- 保证本地生成结果唯一，不保证出口 IP 唯一
- 不自带断点续跑、持久化和历史批次去重

正确用法：

```python
stream = generator.generate(count=1_000_000, country_code="US")
for proxy in stream:
    print(proxy.safe_proxy_url)
```

不要这样做：

```python
items = list(generator.generate(count=1_000_000, country_code="US"))
```

否则会失去流式意义。

### 参数说明

- `count`：生成数量，范围 `0` 到 `10000000`
- `country_code`：国家代码，默认 `"000"`，表示不限国家
- `state_code`：州代码
- `city_code`：城市代码
- `duration_minutes`：会话时长，范围 `1` 到 `1440`
- `protocol`：主代理协议
- `session_id`：自定义会话标识，支持字符串或函数

### session_id 规则

`session_id` 必须是 **32 位小写十六进制字符串**。

#### 单条生成

支持两种传法：

```python
proxy = generator.generate(
    country_code="US",
    session_id="1234567890abcdef1234567890abcdef",
)
```

或者：

```python
def make_session_id() -> str:
    return "1234567890abcdef1234567890abcdef"

proxy = generator.generate(
    country_code="US",
    session_id=make_session_id,
)
```

#### 批量生成

批量场景：

- 不允许传固定字符串 `session_id`
- 允许传零参数函数 `session_id`

例如：

```python
def make_session_id() -> str:
    ...

proxies = generator.generate(
    count=1000,
    country_code="US",
    session_id=make_session_id,
)
```

每条都会调用一次函数。

#### SDK 默认生成规则

如果你不传 `session_id`，SDK 内部会按统一规则生成：

- `16` 位时间戳前缀
- `8` 位随机前缀
- `8` 位递增序号

所以：

- 同一批次 `session_id` 一定不同
- 不同批次 `session_id` 也不同
- 单条和批量使用同一编码体系

### 协议说明

生成器支持这些协议入参：

- `http`
- `https`
- `socks5`
- `socks5h`
- `socket5`
- `socket5h`

规范化规则：

- `socket5` -> `socks5`
- `socket5h` -> `socks5h`

无论主协议是什么，返回对象里都会带：

- `http_url`
- `https_url`
- `socks5_url`
- `socks5h_url`

注意：

- `https` 这里表示“用于 HTTPS 目标站的代理地址”
- 不表示代理网关本身是 HTTPS 服务

### PreparedProxy 返回对象

单条生成时返回 `PreparedProxy`，常用字段包括：

- `proxy_url`：当前主协议对应的完整代理地址
- `safe_proxy_url`：脱敏后的当前主代理地址
- `proxies`：完整多协议代理地址映射
- `safe_proxies`：脱敏后的多协议代理地址映射
- `username`：最终拼接后的代理认证用户名
- `gateway`：网关地址，格式 `host:port`
- `host`
- `port`
- `user`
- `password`
- `masked_user`
- `masked_password`
- `protocol`
- `session_id`
- `country_code`
- `state_code`
- `city_code`
- `duration_minutes`

常用取值方式：

```python
print(proxy.http_url)
print(proxy.https_url)
print(proxy.socks5_url)
print(proxy.socks5h_url)
print(proxy.url_for("socket5"))
```

### 脱敏与导出

脱敏输出建议用于日志：

```python
print(proxy.safe_proxy_url)
print(proxy.masked_user)
print(proxy.masked_password)
print(proxy.to_dict(masked=True))
print(proxy.to_json(masked=True))
print(proxy.explain(masked=True))
```

导出环境变量：

```python
env = proxy.to_env(masked=False)
print(env["HTTP_PROXY"])
print(env["HTTPS_PROXY"])
print(env["ALL_PROXY"])
```

### 地区查询

#### 旧接口：返回代码

```python
countries = generator.list_countries()
states = generator.list_states("US")
cities = generator.list_cities("US")
```

#### 新接口：返回代码 + 名称

```python
countries = generator.list_countries(with_names=True)
states = generator.list_states("US", with_names=True)
cities = generator.list_cities("US", with_names=True)
state_cities = generator.list_cities("US", "1080", with_names=True)
```

返回规则：

- 国家：返回中文名和英文名
- 州、城市：返回源数据中的英文/原始名称

返回结构示例：

```python
{
    "country_code": "US",
    "country_name": "美国",
    "country_name_en": "United States",
    "state_code": "1080",
    "state_name": "Florida",
    "city_code": "100066",
    "city_name": "Kathleen",
}
```

### 参数校验

SDK 会在生成前做严格校验：

- `user_id` 不能为空，只允许字母、数字、下划线、点、短横线
- `password` 不能为空
- `gateway` 必须是官方支持的网关别名或官方 `gate*.ipweb.cc:7778`
- `count` 必须是整数，范围 `0` 到 `10000000`
- `duration_minutes` 必须是整数，范围 `1` 到 `1440`
- `session_id` 必须是 32 位十六进制字符串
- `country_code` 必须是 `000` 或 2 位国家代码
- `state_code` 必须属于指定国家
- `city_code` 必须属于指定国家
- 同时传 `state_code` 和 `city_code` 时，城市必须属于该州

## 请求客户端详解

请求客户端在 `proxy_scheduler_client` 包里。

它的职责是：

- 发送异步请求
- 管理会话状态
- 提供集群和多进程能力
- 输出 curl 命令

它**不负责**：

- 生成代理
- 代理池管理
- 代理评分
- 可用性预检测

### 代理协议支持

当前客户端支持这些代理输入协议：

- `http://`
- `https://`
- `socks5://`
- `socks5h://`
- `socket5://`
- `socket5h://`

其中：

- `socket5` / `socket5h` 会自动归一化
- `socks5h` 在真实请求层会转换为 `socks5 + rdns=True`
- curl 导出层也会正确映射到：
  - `--socks5`
  - `--socks5-hostname`

### ProxyClient

创建方式：

```python
client = ProxyClient(
    proxy_url="http://user:password@gate1.ipweb.cc:7778",
    limits=Limits(concurrency=100, connector_limit=20),
    verbose=False,
)
```

快捷方法：

- `request()`
- `get()`
- `post()`
- `put()`
- `delete()`
- `patch()`
- `head()`
- `options()`

#### 请求头和 Cookie

支持：

- 单次请求 `headers`
- 客户端默认请求头 `default_headers`
- 会话级粘性请求头 `sticky_header()`
- `set_cookie()` / `get_cookies()` / `clear_cookies()`
- `import_state()` / `export_state()`

但要注意：

- `ProxyClient` 本身不会中途自动换代理
- 一个 `ProxyClient` 绑定一个代理
- 要换代理，请新建客户端，或用 `ClientCluster`

#### 429 / 403 / 非 2xx 的处理

当前实现里：

- `429`、`403`、`503` 这类 HTTP 状态码被视为**正常 HTTP 响应**
- 不会自动归类为代理异常
- `response.error is None`
- 但 `response.ok is False`

也就是说：

- 客户端能拿到响应体和状态码
- 是否需要换代理、是否重试，交由调用方决定

### RequestSpec

`RequestSpec` 是纯数据请求模型，支持：

- `method`
- `url`
- `headers`
- `params`
- `data`
- `json`
- `timeout`
- `tag`
- `meta`

适合：

- 集群调度
- 多进程投递
- curl 导出

### Response

`Response` 是和 `aiohttp` 解耦后的标准响应对象。

常用字段：

- `status`
- `headers`
- `url`
- `final_url`
- `method`
- `elapsed_ms`
- `request_tag`
- `proxy_snapshot`
- `error`
- `history`

常用方法：

- `ok`
- `body()`
- `text()`
- `json()`
- `iter_lines()`
- `close()`

### 中文指标快照

`client.metrics.snapshot()` 和 `cluster.metrics_snapshot()` 现在都会直接返回中文 key。

例如：

- `请求启动数`
- `请求完成数`
- `请求异常数`
- `成功请求数`
- `429限流次数`
- `成功请求平均耗时毫秒`
- `成功请求P50耗时毫秒`
- `成功请求P99耗时毫秒`
- `热点耗时区间`
- `成功状态分布`
- `状态分布`
- `错误分布`

所以你在并发压测里直接调用：

```python
cluster.metrics_snapshot()
```

就能拿到完整统计。

### ClientCluster

`ClientCluster` 适合“一条代理一个 `ProxyClient`”的并发场景。

核心能力：

- `request()`
- `stream()`
- `gather()`
- `metrics_snapshot()`

特点：

- 按每个 `ProxyClient` 的并发上限做窗口分片
- 不会把集群总窗口压到单个客户端
- `FailurePolicy.RETRY_ON_NEXT`：失败时切到下一个客户端
- `FailurePolicy.SKIP`：当前请求只试当前路由命中的一个客户端
- `FailurePolicy.FAIL_ALL`：当前路由命中的客户端失败后立即结束

### ProcessPoolRunner

适合更高并发、更高 CPU 占用场景。

特点：

- 多进程运行
- `worker_factory` 必须是可 pickle 的顶层函数
- worker 异常退出时会重启并重投受影响请求
- `stream()` / `gather()` 在同一个 runner 上是串行批次复用
- worker 重启后不会自动继承旧进程内的 Cookie 和登录态

### curl 导出

#### RequestSpec.to_curl()

导出“请求规格视角”的 curl：

```python
spec = RequestSpec(
    method="POST",
    url="https://example.com/api",
    headers={"x-trace-id": "demo"},
    json={"name": "alice"},
    meta={"verify": False},
)

print(spec.to_curl(shell="bash"))
print(spec.to_curl(shell="cmd", masked=True))
```

#### ProxyClient.request_to_curl()

导出“客户端最终发送态”的 curl：

```python
print(
    client.request_to_curl(
        "GET",
        "https://example.com/profile",
        shell="powershell",
        masked=False,
    )
)
```

两者区别：

- `RequestSpec.to_curl()`：只关心请求规格本身
- `ProxyClient.request_to_curl()`：会自动合并代理地址、默认头、sticky headers、Cookie 和超时

#### shell 适配

支持：

- `shell="auto"`
- `shell="bash"`
- `shell="cmd"`
- `shell="powershell"`

规则：

- `auto`：Windows 下默认输出 `cmd` 风格，其他平台默认输出 `bash`
- `cmd`：输出 `curl.exe ...`
- `powershell`：输出 `curl.exe --% ...`

所以：

- 在 `cmd.exe` 里直接粘贴执行，请用 `shell="cmd"`
- 在 PowerShell 里直接粘贴执行，请用 `shell="powershell"`

#### 默认脱敏策略

当前默认：

- `masked=False`

也就是默认优先导出**可执行复现命令**。

如果用于日志，请显式传：

```python
masked=True
```

脱敏内容包括：

- 代理认证
- `Authorization`
- `Proxy-Authorization`
- `Cookie`
- URL 查询参数中的常见敏感字段
- JSON / 表单中的常见敏感字段

## 版本 0.1.2 重点变更

相对早期版本，`0.1.2` 的重点能力包括：

- 生成器与请求客户端拆分为两个导入命名空间
- 统一入口 `generate()` 支持大批量自动流式输出
- `session_id` 生成规则升级为时间戳前缀 + 随机前缀 + 递增序号
- 批量场景支持自定义 `session_id` 生成函数
- 地区查询支持返回国家中英文名、州/城市名称
- 请求客户端支持 curl 导出
- curl 导出支持 `bash` / `cmd` / `powershell`
- `cluster.metrics_snapshot()` 和 `client.metrics.snapshot()` 返回中文指标 key
- 请求层支持 `socket5` / `socket5h` 别名和 `socks5h` 正确适配

## 示例文件

你可以直接参考这些示例：

- [generate_proxy.py](E:/github/xiaoli-proxy-tools/examples/generator/generate_proxy.py)
- [generate_million_proxies.py](E:/github/xiaoli-proxy-tools/examples/generator/generate_million_proxies.py)
- [proxy_client_demo.py](E:/github/xiaoli-proxy-tools/examples/client/proxy_client_demo.py)
- [real_proxy_request.py](E:/github/xiaoli-proxy-tools/examples/client/real_proxy_request.py)
- [real_site_with_headers.py](E:/github/xiaoli-proxy-tools/examples/client/real_site_with_headers.py)
- [request_to_curl_demo.py](E:/github/xiaoli-proxy-tools/examples/client/request_to_curl_demo.py)

## 发布范围

当前构建包会包含两个 Python 包：

```text
proxy_scheduler/
proxy_scheduler_client/
proxy_scheduler/data/geo_codes.min.json
```

运行时固定使用内置：

- `proxy_scheduler/data/geo_codes.min.json`

根目录的：

- `geo_codes.xlsx`

只作为开发阶段生成快照的数据源，不建议打进发布产物。

当前 SDK 不包含这些能力：

- 代理池管理
- 代理评分
- 自动可用性检测
- 出口 IP 去重保证
- 浏览器自动化
