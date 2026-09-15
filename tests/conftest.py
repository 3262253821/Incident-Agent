"""测试会话的进程级隔离（与业务代码无关，只影响 pytest 进程的环境）。

这套测试从不访问真实网络：HTTP 全部由 ``httpx.MockTransport`` 或进程内适配器
接管，数据库是 SQLite 内存库。但 ``httpx.Client`` 默认 ``trust_env=True``，会在
构造时读取开发机上的代理变量，于是**测试结果会被机器环境左右**。

实测的失败形态（本机 ``NO_PROXY`` 里含 IPv6 方括号写法时）：

```text
httpx.InvalidURL: Invalid port: ':1]'
```

它在任何断言之前就抛出，导致 23 条与代理毫无关系的测试失败（
``tests/test_error_handling.py``、``tests/test_knowledge_base_authorizer.py`` 等）。
因此这里在会话开始时清掉代理变量，让 ``httpx`` 不再读到它们，保证
``py -m pytest tests -q`` 在任何开发机上结果一致。
"""

from __future__ import annotations

import os

_PROXY_VARIABLES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)


def pytest_configure(config) -> None:
    """Remove proxy variables before any test builds an ``httpx`` client."""

    for name in _PROXY_VARIABLES:
        os.environ.pop(name, None)
