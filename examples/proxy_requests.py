from proxy_scheduler import ProxySchedulerClient

with ProxySchedulerClient(
    user_id="YOU_USER_ID",
    password="YOU_USER_PASSWORD",
    gateway="apac",
) as client:
    result = client.get("https://api.ipify.org?format=json", max_retries=0, timeout=20)
    print(result.status_code)
    print(result.text)

