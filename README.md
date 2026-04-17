# proxy_scheduler

`proxy_scheduler` 是一个面向 IPWeb 动态代理的 Python SDK。
官方文档：https://docs.ipweb.cc/user-guide/

当前实现有两条主要使用路径：

1. 单独生成动态代理
2. 使用内置客户端直接发起请求

## 安装

```bash
pip install -r requirements.txt
```

如果你是在仓库内直接运行示例，也可以使用虚拟环境里的 Python：

```bash
.\venv\Scripts\python.exe examples\test_proxy_requests.py
```

## 核心行为

- 每次请求尝试都会即时生成一条新的动态代理
- 默认请求后端是 `curl_cffi`
- 也可以切换为 `requests`
- SDK 返回的是 `RequestResult`
- `RequestResult` 兼容常见的 `requests.Response` 读取方式，例如 `.text`、`.content`、`.json()`、`.ok`

## 方式一：单独生成动态代理

适合你只想拿到代理地址，不想让 SDK 直接发请求的场景。

```python
from proxy_scheduler import DynamicProxyGenerator

generator = DynamicProxyGenerator(
    user_id="YOU_USER_ID",
    password="YOU_USER_PASSWORD",
    gateway="apac",
)

proxy = generator.generate(
    country_code="000",
    duration_minutes=5,
)

print(proxy.proxy_url)
print(proxy.proxies)
print(proxy.username)
print(proxy.gateway)
```

返回对象 `PreparedProxy` 包含这些常用字段：

- `proxy.proxy_url`
- `proxy.proxies`
- `proxy.username`
- `proxy.gateway`

批量生成：

```python
proxies = generator.generate_many(
    5,
    country_code="US",
    duration_minutes=5,
)
```

也可以通过客户端暴露的内置入口生成：

```python
from proxy_scheduler import ProxySchedulerClient

with ProxySchedulerClient(
    user_id="YOU_USER_ID",
    password="YOU_USER_PASSWORD",
    gateway="apac",
) as client:
    proxy = client.generate_proxy(country_code="000", duration_minutes=5)
    proxy_list = client.generate_proxies(3, country_code="US", duration_minutes=5)
```

## 方式二：使用内置客户端直接请求

适合你希望 SDK 直接完成代理生成、请求发送、重试和响应封装。

### 最简单的 GET

```python
from proxy_scheduler import ProxySchedulerClient

with ProxySchedulerClient(
    user_id="YOU_USER_ID",
    password="YOU_USER_PASSWORD",
    gateway="apac",
) as client:
    result = client.get(
        "https://api.ipify.org?format=json",
        max_retries=0,
        timeout=20,
    )

    print(result.status_code)
    print(result.text)
    print(result.json())
    print(result.ok)
```

### POST 请求

```python
from proxy_scheduler import ProxySchedulerClient

with ProxySchedulerClient(
    user_id="YOU_USER_ID",
    password="YOU_USER_PASSWORD",
    gateway="apac",
) as client:
    result = client.post(
        "https://httpbin.org/post",
        body={"name": "demo"},
        headers={"Content-Type": "application/json"},
        max_retries=1,
    )

    print(result.status_code)
    print(result.text)
```

### 异步调用

```python
import asyncio
from proxy_scheduler import ProxySchedulerClient


async def main():
    async with_client = ProxySchedulerClient(
        user_id="YOU_USER_ID",
        password="YOU_USER_PASSWORD",
        gateway="apac",
    )
    try:
        result = await with_client.async_get("https://api.ipify.org?format=json")
        print(result.text)
    finally:
        with_client.shutdown()


asyncio.run(main())
```

### 批量并发

```python
import asyncio
from proxy_scheduler import ProxySchedulerClient, TaskConfig


async def main():
    client = ProxySchedulerClient(
        user_id="YOU_USER_ID",
        password="YOU_USER_PASSWORD",
        gateway="apac",
    )
    try:
        tasks = [
            TaskConfig(url="https://httpbin.org/ip", method="GET"),
            TaskConfig(url="https://httpbin.org/headers", method="GET"),
        ]
        results = await client.async_batch(tasks, concurrency=2)
        for result in results:
            print(result.status_code, result.success)
    finally:
        client.shutdown()


asyncio.run(main())
```

## 切换请求后端

默认是 `TransportBackend.CURL_CFFI`。

```python
from proxy_scheduler import ProxySchedulerClient, TransportBackend

client = ProxySchedulerClient(
    user_id="YOU_USER_ID",
    password="YOU_USER_PASSWORD",
    gateway="apac",
    default_backend=TransportBackend.CURL_CFFI,
)
```

如果目标站不需要 TLS 指纹模拟，也可以切到 `requests`：

```python
from proxy_scheduler import ProxySchedulerClient, TransportBackend

client = ProxySchedulerClient(
    user_id="YOU_USER_ID",
    password="YOU_USER_PASSWORD",
    gateway="apac",
    default_backend=TransportBackend.REQUESTS,
)
```

## 常用参数

`ProxySchedulerClient.get()` / `post()` 常见参数：

- `country_code`
- `sticky`
- `site_id`
- `timeout`
- `max_retries`
- `headers`

`generate_proxy()` 常见参数：

- `country_code`
- `duration_minutes`
- `session_id`
- `state_code`
- `city_code`

## 运行模式说明

客户端当前不是代理池模式。

```python
with ProxySchedulerClient(
    user_id="YOU_USER_ID",
    password="YOU_USER_PASSWORD",
    gateway="apac",
) as client:
    print(client.pool_stats())
```

返回值为：

```python
{"enabled": False, "mode": "direct_dynamic_proxy"}
```

这表示当前请求链路是：

1. 为本次请求生成一条动态代理
2. 发送请求
3. 失败时重试，并为下一次尝试重新生成代理

## 示例文件

- `examples/generate_proxy.py`
- `examples/test_proxy_requests.py`
- `examples/advanced_proxy_usage.py`

## 注意事项

- 不要把真实 `user_id`、`password`、完整 `proxy_url` 提交到仓库
- `proxy_url` 中包含明文代理凭证，打印和记录日志时应谨慎
- 如果你只想拿代理，不要调用 `client.get()`，直接使用 `DynamicProxyGenerator` 或 `client.generate_proxy()`
