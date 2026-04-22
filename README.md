# ipweb-proxy-sdk

当前项目已经按功能拆分为两部分：

- `proxy_scheduler`：负责动态代理生成。
- `proxy_client`：负责通用异步代理请求。

如果你的目标只是“生成一条可直接使用的动态代理地址”，只需要使用 `proxy_scheduler`。

## 目录结构

```text
.
|-- proxy_scheduler/                 # 动态代理生成器
|-- proxy_client/                    # 通用异步代理客户端
|-- examples/
|   |-- generator/                   # 生成器示例
|   `-- client/                      # 客户端示例
`-- base_client.py                   # 异步客户端兼容导入入口
```

## 安装

安装本地开发依赖：

```bash
pip install -r requirements.txt
```

如果你只需要异步客户端依赖，也可以单独安装：

```bash
pip install "curl-cffi>=0.14.0"
```

## 动态代理总览

动态代理生成器不会自己发请求，它只负责根据你的账号、地区、时长、会话参数，生成一条或多条可直接交给外部客户端使用的代理地址。

主要入口：

```python
from proxy_scheduler import DynamicProxyGenerator
```

核心类：

- `DynamicProxyGenerator`
  统一入口，负责单条或批量生成代理。
- `PreparedProxy`
  单条代理的标准返回对象，内含 `proxy_url`、`proxies`、`username`、`gateway` 等字段。
- `ProxyNode`
  结构化代理节点对象，适合高级集成或自定义调度。

## 快速开始

最小示例：

```python
from proxy_scheduler import DynamicProxyGenerator

generator = DynamicProxyGenerator(
    user_id="YOU_USER_ID",
    password="YOU_USER_PASSWORD",
    gateway="apac",
)

proxy = generator.generate(
    country_code="US",
)

print(proxy.proxy_url)
print(proxy.proxies)
```

典型输出对象说明：

```python
print(proxy.proxy_url)     # 当前主代理地址，取决于 protocol 参数
print(proxy.http_url)      # HTTP 代理地址
print(proxy.https_url)     # HTTPS 代理地址
print(proxy.socks5_url)    # SOCKS5 代理地址
print(proxy.socks5h_url)   # SOCKS5H 代理地址
print(proxy.proxies)       # 所有协议的代理字典
print(proxy.username)      # 最终拼接后的代理用户名
print(proxy.gateway)       # 实际使用的网关
```

## DynamicProxyGenerator 初始化参数

创建生成器：

```python
from proxy_scheduler import DynamicProxyGenerator

generator = DynamicProxyGenerator(
    user_id="YOU_USER_ID",
    password="YOU_USER_PASSWORD",
    gateway="apac",
)
```

参数说明：

- `user_id`
  代理账号用户标识，必填，不能为空。
- `password`
  代理账号密码，必填，不能为空。
- `gateway`
  网关入口，默认 `apac`。

支持的常用网关别名：

- `us`
- `americas`
- `america`
- `apac`
- `asia`
- `emea`
- `europe`
- `global`

网关别名会被自动转换为真实隧道地址：

- `us` / `americas` / `global` -> `gate1.ipweb.cc:7778`
- `apac` / `asia` -> `gate2.ipweb.cc:7778`
- `emea` / `europe` -> `gate3.ipweb.cc:7778`

如果你传入的是自定义主机名，也支持：

```python
generator = DynamicProxyGenerator(
    user_id="YOU_USER_ID",
    password="YOU_USER_PASSWORD",
    gateway="custom-gateway.example.com:7778",
)
```

## generate() 详细说明

`generate()` 是统一入口：

```python
proxy = generator.generate(...)
proxies = generator.generate(count=10, ...)
```

参数说明：

- `count`
  生成数量，默认 `1`。
  `count=1` 返回 `PreparedProxy`。
  `count>1` 返回 `list[PreparedProxy]`。
  `count=0` 返回空列表。
- `country_code`
  国家代码，默认 `"000"`。
  `"000"` 表示不限制国家。
  指定国家时必须传 2 位 ISO 大写国家代码，例如 `"US"`、`"GB"`、`"JP"`。
- `duration_minutes`
  会话时长，默认 `5`，必须是大于 `0` 的整数。
- `session_id`
  自定义会话标识，仅单条生成时可用。
  必须是 32 位十六进制字符串，例如 `32` 位小写 `uuid4().hex`。
- `state_code`
  州代码，只有在指定了具体 `country_code` 时才允许传入。
- `city_code`
  城市代码，只有在指定了具体 `country_code` 时才允许传入。
  如果同时传了 `state_code`，则必须保证 `city_code` 属于该州。
- `protocol`
  选择当前主代理地址对应的协议。

支持的协议值：

- `http`
- `https`
- `socks5`
- `socks5h`
- `socket5`
- `socket5h`

其中：

- `socket5` 会自动规范化为 `socks5`
- `socket5h` 会自动规范化为 `socks5h`
- 即使你选择了某个 `protocol`，`PreparedProxy.proxies` 里仍会包含多协议地址映射

## 单条代理生成

默认单条生成：

```python
from proxy_scheduler import DynamicProxyGenerator

generator = DynamicProxyGenerator(
    user_id="YOU_USER_ID",
    password="YOU_USER_PASSWORD",
    gateway="apac",
)

proxy = generator.generate(
    country_code="US",
    duration_minutes=10,
    protocol="http",
)

print(proxy.proxy_url)
print(proxy.proxies)
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

print(proxy.proxy_url)
```

指定固定 `session_id`：

```python
proxy = generator.generate(
    country_code="US",
    duration_minutes=15,
    session_id="1234567890abcdef1234567890abcdef",
    protocol="http",
)

print(proxy.username)
print(proxy.proxy_url)
```

说明：

- 如果不传 `session_id`，SDK 会自动生成一个 32 位十六进制字符串。
- 自动生成逻辑等价于 `uuid.uuid4().hex`。

## 批量代理生成

批量生成使用同一个入口：

```python
from proxy_scheduler import DynamicProxyGenerator

generator = DynamicProxyGenerator(
    user_id="YOU_USER_ID",
    password="YOU_USER_PASSWORD",
    gateway="apac",
)

proxies = generator.generate(
    count=10,
    country_code="US",
    duration_minutes=5,
    protocol="http",
)

for item in proxies:
    print(item.proxy_url)
```

也可以继续使用兼容方法：

```python
proxies = generator.generate_many(
    10,
    country_code="US",
    duration_minutes=5,
    protocol="http",
)
```

批量生成规则：

- `count > 1` 时不能传 `session_id`
- 每一条代理都会自动生成新的 `session_id`
- 返回值始终为 `list[PreparedProxy]`

## 返回对象说明

### PreparedProxy

`generate()` 单条返回 `PreparedProxy`。

常用字段：

- `proxy.proxy_url`
  当前主协议对应的代理地址。
- `proxy.proxies`
  所有协议的映射字典，包含：
  `http`、`https`、`socks5`、`socks5h`
- `proxy.username`
  拼接后的最终代理用户名，格式为：
  `user_id_country_state_city_duration_session_id`
- `proxy.gateway`
  当前代理使用的真实网关地址。

常用属性：

- `proxy.http_url`
- `proxy.https_url`
- `proxy.socks5_url`
- `proxy.socks5h_url`

按协议取地址：

```python
print(proxy.url_for("http"))
print(proxy.url_for("socks5"))
print(proxy.url_for("socket5"))
```

### ProxyNode

如果你需要更结构化的节点对象，可以使用：

```python
node = generator.generate_node(
    country_code="US",
    duration_minutes=5,
    protocol="http",
)

print(node.session_id)
print(node.proxy_url)
print(node.proxies)
print(node.key)
```

字段说明：

- `node.session_id`
- `node.proxy_url`
- `node.proxies`
- `node.country_code`
- `node.duration_minutes`
- `node.key`

其中 `key` 当前等于 `session_id`。

## 批量提取代理地址

如果你只想从一批 `PreparedProxy` 里拿出某一种协议的地址，可以使用：

```python
proxies = generator.generate(
    count=5,
    country_code="US",
    protocol="http",
)

urls = DynamicProxyGenerator.proxy_urls(proxies, protocol="socks5")
print(urls)
```

## 地区参数校验规则

地区参数会根据仓库内置的地理数据进行校验。数据来源优先级如下：

- 如果根目录 `geo_codes.xlsx` 存在，且比内置快照新，则优先读取它
- 否则读取 `proxy_scheduler/data/geo_codes.min.json`

校验规则：

- `country_code="000"` 时，不允许传 `state_code` 和 `city_code`
- 指定国家时，`country_code` 必须是 2 位大写国家代码
- `state_code` 必须属于该国家
- `city_code` 必须属于该国家
- 如果同时传了 `state_code` 和 `city_code`，则 `city_code` 必须属于该州

错误示例：

```python
generator.generate(
    country_code="000",
    state_code="2079",
)
```

上面会抛出异常，因为全局国家模式下不能再限制州。

## session_id 规则

`session_id` 必须满足：

- 长度固定 `32`
- 只能是十六进制字符
- SDK 内部会统一转成小写

正确示例：

```python
session_id = "1234567890abcdef1234567890abcdef"
```

错误示例：

```python
session_id = "abc"
session_id = "G234567890abcdef1234567890abcdef"
session_id = "1234567890abcdef1234567890abcdeZ"
```

## 代理用户名格式

最终生成的代理用户名格式如下：

```text
user_id_country_code_state_code_city_code_duration_minutes_session_id
```

例如：

```text
B_36424_US_2079_75544_5_1234567890abcdef1234567890abcdef
```

这也是 `PreparedProxy.username` 的内容。

## 外部客户端适配

`PreparedProxy` 已经内置了常见客户端的适配方法：

```python
proxy = generator.generate(
    country_code="US",
    protocol="socks5",
)
```

### requests

```python
requests_proxies = proxy.for_client("requests", protocol="socks5")
print(requests_proxies)
```

### httpx

```python
httpx_proxy = proxy.for_client("httpx", protocol="socks5")
print(httpx_proxy)
```

### aiohttp

```python
aiohttp_proxy = proxy.for_client("aiohttp", protocol="http")
print(aiohttp_proxy)
```

注意：

- `aiohttp` 原生只支持 HTTP 代理
- 如果你传 `socks5` 给 `aiohttp`，会抛出异常
- 使用 SOCKS 代理时应改用 `aiohttp_socks`

### aiohttp_socks

```python
aiohttp_socks_proxy = proxy.for_client("aiohttp_socks", protocol="socks5")
print(aiohttp_socks_proxy)
```

### playwright

```python
playwright_proxy = proxy.for_client("playwright", protocol="socks5")
print(playwright_proxy)
```

## 常见用法组合

全局随机代理：

```python
proxy = generator.generate(
    country_code="000",
    protocol="http",
)
```

指定国家代理：

```python
proxy = generator.generate(
    country_code="US",
    protocol="http",
)
```

指定国家 + 州：

```python
proxy = generator.generate(
    country_code="US",
    state_code="2079",
    protocol="http",
)
```

指定国家 + 州 + 城市：

```python
proxy = generator.generate(
    country_code="US",
    state_code="2079",
    city_code="75544",
    protocol="socks5",
)
```

批量快速生成：

```python
proxies = generator.generate(
    count=100,
    country_code="US",
    protocol="http",
)
```

## 常见异常

以下情况会抛出 `ValueError`：

- `user_id` 为空
- `password` 为空
- `count < 0`
- `count > 1` 时仍传了 `session_id`
- `duration_minutes` 不是整数或小于等于 `0`
- `session_id` 不是 32 位十六进制字符串
- `country_code` 格式错误
- `country_code` 不在内置地区数据中
- `state_code` 不属于该国家
- `city_code` 不属于该国家
- `city_code` 与 `state_code` 不匹配
- `protocol` 不在支持列表内

## 异步客户端

动态代理生成和异步请求客户端已经分开存放。

如果你需要在生成代理后直接发请求，请使用：

```python
from proxy_client import AsyncProxyClient
```

配合生成器的最小示例：

```python

import asyncio
from proxy_client import AsyncProxyClient
from proxy_scheduler import DynamicProxyGenerator

async def main() -> None:
    generator = DynamicProxyGenerator(
    user_id="YOU_USER_ID",
    password="YOU_USER_PASSWORD",
    gateway="apac",
    )
    proxy = generator.generate(country_code="US")
    async with AsyncProxyClient(
        proxy_source=proxy.proxy_url,
        retry_count=2,
        verbose=True,
    ) as client:
        response = await client.get(
            "https://api.ipify.org?format=json",
            timeout=30,
            verify=False,
        )
        print(response.status_code)
        print(response.text)
if __name__ == '__main__':
    asyncio.run(main())
```

## 示例文件

- `examples/generator/generate_proxy.py`
- `examples/client/async_proxy_client_demo.py`
- `examples/generate_proxy.py`
- `examples/async_proxy_client_demo.py`
