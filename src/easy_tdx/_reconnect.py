"""连接重连与心跳策略的共享定义。

将原本在 ``client.py`` 与 ``mac/client.py`` 各自定义的 ``_RETRY_DELAYS``
提取到此统一来源，并供扩展行情 client（``ex/*``）复用，消除"6 处副本里
两套不一致韧性策略"的问题（审计报告 #2）。

复审（L1）补充：4 个 async client（A股 / MAC / 扩展行情 / 扩展 MAC）的
``_start_heartbeat`` / ``_stop_heartbeat`` / ``_heartbeat_loop`` 三件套此前
逐字节重复（仅心跳命令和 logger 名不同）。这里抽出
``AsyncHeartbeatMixin`` 收敛这些副本——子类只需实现 ``_heartbeat_cmd()``
返回一个 awaitable 即可，未来改心跳策略只需改一处。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable

from .exceptions import TdxConnectionError, TdxDecodeError

# 连接断开时的指数退避序列（秒）。每次重连失败后按此序列 sleep 再重试，
# 共 4 次尝试（0.1 + 0.5 + 1.0 + 2.0 = 3.6s 总退避时间）。
# A 股 / MAC / 扩展行情 / 扩展 MAC 共 8 个 client 统一使用此序列。
_RETRY_DELAYS: tuple[float, ...] = (0.1, 0.5, 1.0, 2.0)

# 心跳失败时收窄的可重试异常（审计 #6）：仅连接/解析类异常视为"本次失败、
# 等下次重试"，不吞掉代码 bug 等非预期异常。子类无需重复声明此元组。
# exceptions 模块为纯定义、零导入，顶部导入无循环依赖风险。
_HEARTBEAT_RETRYABLE: tuple[type[BaseException], ...] = (
    OSError,
    TdxConnectionError,
    TdxDecodeError,
)


class AsyncHeartbeatMixin:
    """async client 心跳三件套的共享实现（审计复审 L1）。

    子类约定：
        - 在 ``__init__`` 中设置 ``self._heartbeat_interval: float`` 与
          ``self._heartbeat_task: asyncio.Task | None = None``；
        - 实现 ``_heartbeat_cmd()``，返回一个 awaitable（通常是一个轻量
          业务请求，用于保活并触发断线重连）。

    收敛后 ``_start_heartbeat`` / ``_stop_heartbeat`` / ``_heartbeat_loop``
    只此一份实现；心跳异常范围统一收窄为 (OSError, TdxConnectionError,
    TdxDecodeError)（审计 #6）。
    """

    # 类型提示（实际由子类 __init__ 赋值；此处仅服务于静态检查与文档）
    _heartbeat_interval: float
    _heartbeat_task: asyncio.Task[None] | None

    def _heartbeat_cmd(self) -> Awaitable[object]:
        """返回心跳使用的轻量请求 awaitable。子类必须覆写。"""
        raise NotImplementedError

    def _start_heartbeat(self) -> None:
        """启动后台心跳任务（若已在跑则先取消旧任务）。"""
        if self._heartbeat_interval <= 0:
            return
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _stop_heartbeat(self) -> None:
        """停止并清理心跳任务。"""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

    async def _heartbeat_loop(self) -> None:
        """心跳循环：定期发送轻量级请求保活。

        失败语义：连接/解析类异常属于"本次失败、等下次重试"，下一次正常的
        业务请求或下一次心跳会通过 ``_execute`` 触发重连。非预期异常
        （代码 bug）不被吞掉，会冒泡打断心跳任务（审计 #6）。
        """
        while True:
            try:
                await asyncio.sleep(self._heartbeat_interval)
                await self._heartbeat_cmd()
            except asyncio.CancelledError:
                break
            except _HEARTBEAT_RETRYABLE:
                logging.getLogger(__name__).debug(
                    "心跳失败，等待下次业务请求触发重连", exc_info=True
                )
