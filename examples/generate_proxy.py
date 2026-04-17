import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from proxy_scheduler import DynamicProxyGenerator


generator = DynamicProxyGenerator(
    user_id="YOU_USER_ID",
    password="YOU_USER_PASSWORD",
    gateway="apac",
)

proxy = generator.generate(country_code="000", duration_minutes=5)

print(proxy.proxy_url)
print(proxy.proxies)
print(proxy.username)
print(proxy.gateway)
