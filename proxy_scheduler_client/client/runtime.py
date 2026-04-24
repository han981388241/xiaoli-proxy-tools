"""
异步客户端运行时辅助工具。
"""

from __future__ import annotations

import os
import platform
import asyncio
import logging
from typing import Any

_LOGGER = logging.getLogger("proxy_scheduler_client.runtime")


def install_fast_event_loop(*, verbose: bool = False) -> bool:
    """
    在支持的平台上安装 uvloop 事件循环。

    Args:
        verbose (bool): 是否打印中文调试日志。

    Returns:
        bool: 成功启用 uvloop 返回 True，否则返回 False。
    """

    if os.name == "nt":
        if verbose:
            _log_runtime_message("[运行时] 跳过 uvloop - URL: - 状态: Windows 不支持 重试: 0/0 代理: -")
        return False

    try:
        import uvloop
    except ImportError:
        if verbose:
            _log_runtime_message("[运行时] 跳过 uvloop - URL: - 状态: 未安装 重试: 0/0 代理: -")
        return False

    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    if verbose:
        _log_runtime_message("[运行时] 启用 uvloop - URL: - 状态: 成功 重试: 0/0 代理: -")
    return True


def runtime_snapshot() -> dict[str, Any]:
    """
    返回当前运行时快照。

    Returns:
        dict[str, Any]: 运行时信息。
    """

    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "os_name": os.name,
        "cpu_count": os.cpu_count() or 1,
    }


def recommend_process_count(*, clients_per_process: int = 4) -> int:
    """
    推荐多进程数量。

    Args:
        clients_per_process (int): 每进程建议承载的客户端实例数量。

    Returns:
        int: 推荐进程数量。
    """

    cpu_count = os.cpu_count() or 1
    divisor = max(1, clients_per_process)
    return max(1, cpu_count // divisor)


def _log_runtime_message(message: str) -> None:
    """
    输出运行时模块日志。

    Args:
        message (str): 日志内容。

    Returns:
        None: 无返回值。
    """

    if not logging.getLogger().handlers and not _LOGGER.handlers:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
    _LOGGER.info(message)


__all__ = ["install_fast_event_loop", "recommend_process_count", "runtime_snapshot"]
