# ipweb-proxy-sdk

IPWEB 动态代理生成 SDK。

当前项目只保留代理生成功能，不内置任何请求客户端，不负责发起 HTTP 请求、不维护代理池、不做代理评分。

## 目录结构

```text
.
|-- proxy_scheduler/                 # 动态代理生成器
|-- proxy_scheduler/data/            # 内置地区数据快照
|-- examples/generator/              # 生成器示例
|-- pyproject.toml                   # 打包配置
`-- README.md                        # 使用说明
```

## 安装

本地开发依赖：

```bash
pip install -r requirements.txt
```

安装 SDK 后使用：

```python
from proxy_scheduler import DynamicProxyGenerator
```

## 功能范围

SDK 提供以下能力：

- 生成单条动态代理
- 批量生成动态代理
- 指定国家、州、城市生成代理
- 指定代理协议生成代理
- 指定会话时长生成代理
- 指定 `session_id` 生成固定会话代理
- 返回完整代理 URL 和拆分字段
- 校验国家、州、城市参数

SDK 不提供以下能力：

- 不发起请求
- 不内置同步/异步/curl 请求客户端
- 不维护代理池
- 不做代理评分
- 不判断代理是否可用

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

    print("[生成器示例] 开始生成代理 - country_code: US")
    proxy = generator.generate(
        country_code="US",
        duration_minutes=5,
        protocol="http",
    )

    print(f"[生成器示例] 生成完成 - proxy_url: {proxy.proxy_url}")
    print(f"[生成器示例] 代理主机 - host: {proxy.host}")
    print(f"[生成器示例] 代理端口 - port: {proxy.port}")
    print(f"[生成器示例] 代理用户 - user: {proxy.user}")
    print(f"[生成器示例] 代理密码 - password: {proxy.password}")
    print(f"[生成器示例] 代理协议 - protocol: {proxy.protocol}")


if __name__ == "__main__":
    main()
```

## DynamicProxyGenerator

创建生成器：

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
- `gateway`：代理网关，默认 `apac`。

支持的网关别名：

- `us`
- `americas`
- `america`
- `apac`
- `asia`
- `emea`
- `europe`
- `global`

网关映射：

- `us` / `americas` / `america` / `global` -> `gate1.ipweb.cc:7778`
- `apac` / `asia` -> `gate2.ipweb.cc:7778`
- `emea` / `europe` -> `gate3.ipweb.cc:7778`

也支持自定义网关：

```python
generator = DynamicProxyGenerator(
    user_id="YOU_USER_ID",
    password="YOU_USER_PASSWORD",
    gateway="custom-gateway.example.com:7778",
)
```

## generate()

`generate()` 是统一生成入口。

```python
proxy = generator.generate(...)
proxies = generator.generate(count=10, ...)
```

参数说明：

- `count`：生成数量，默认 `1`。
- `country_code`：国家代码，默认 `"000"`，表示不限制国家。
- `duration_minutes`：会话时长，默认 `5`。
- `session_id`：自定义会话标识，仅单条生成时可用。
- `state_code`：州代码。
- `city_code`：城市代码。
- `protocol`：当前主代理协议。

返回规则：

- `count=1` 返回 `PreparedProxy`。
- `count>1` 返回 `list[PreparedProxy]`。
- `count=0` 返回空列表。
- `count>1` 时不能传 `session_id`。

## 协议支持

支持协议：

- `http`
- `https`
- `socks5`
- `socks5h`
- `socket5`
- `socket5h`

说明：

- `socket5` 会自动规范化为 `socks5`。
- `socket5h` 会自动规范化为 `socks5h`。
- 无论当前主协议是什么，返回对象都会保留所有协议地址。

## PreparedProxy

`generate()` 单条返回 `PreparedProxy`。

常用字段：

- `proxy.proxy_url`：当前主协议对应的完整代理地址。
- `proxy.proxies`：全部协议代理地址映射。
- `proxy.username`：最终拼接后的代理用户名。
- `proxy.gateway`：实际使用的网关，格式为 `host:port`。
- `proxy.host`：代理网关主机。
- `proxy.port`：代理网关端口。
- `proxy.user`：代理认证用户名，等同于 `proxy.username`。
- `proxy.password`：代理认证密码。
- `proxy.protocol`：当前主代理协议。

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

## 单条代理生成

```python
proxy = generator.generate(
    country_code="US",
    duration_minutes=10,
    protocol="http",
)

print(proxy.proxy_url)
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

## 批量代理生成

```python
proxies = generator.generate(
    count=10,
    country_code="US",
    duration_minutes=5,
    protocol="http",
)

for item in proxies:
    print(item.proxy_url)
```

也可以使用兼容方法：

```python
proxies = generator.generate_many(
    10,
    country_code="US",
    duration_minutes=5,
    protocol="http",
)
```

## ProxyNode

如果需要结构化节点对象，可以使用：

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

## 批量提取代理地址

```python
proxies = generator.generate(
    count=5,
    country_code="US",
    protocol="http",
)

urls = DynamicProxyGenerator.proxy_urls(proxies, protocol="socks5")
print(urls)
```

## 地区参数校验

地区参数会根据仓库内置地区数据校验。

数据来源优先级：

- 如果根目录 `geo_codes.xlsx` 存在，且比内置快照新，则优先读取它。
- 否则读取 `proxy_scheduler/data/geo_codes.min.json`。

校验规则：

- `country_code="000"` 时，不允许传 `state_code` 和 `city_code`。
- 指定国家时，`country_code` 必须是 2 位大写国家代码。
- `state_code` 必须属于该国家。
- `city_code` 必须属于该国家。
- 同时传 `state_code` 和 `city_code` 时，`city_code` 必须属于该州。

## session_id 规则

`session_id` 必须满足：

- 长度固定 `32`。
- 只能是十六进制字符。
- SDK 内部会统一转成小写。

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

最终生成的代理用户名格式：

```text
user_id_country_code_state_code_city_code_duration_minutes_session_id
```

示例：

```text
B_36424_US_2079_75544_5_1234567890abcdef1234567890abcdef
```

## 示例文件

- `examples/generator/generate_proxy.py`
