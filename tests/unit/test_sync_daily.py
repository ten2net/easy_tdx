"""sync-daily 分页拉取重试容错测试。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from easy_tdx.cli.cmd_offline import _fetch_all_daily_bars
from easy_tdx.exceptions import TdxDecodeError


class TestFetchAllDailyBarsRetry:
    """_fetch_all_daily_bars 单页失败重试回归测试。"""

    def test_retry_succeeds_on_transient_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """某页偶尔失败，重试后成功，应继续完成同步。"""
        from easy_tdx.models.enums import KlineCategory, Market

        client = MagicMock()
        calls: list[tuple[object, ...]] = []

        def fake_get_security_bars(
            market: Market,
            code: str,
            category: KlineCategory,
            start: int,
            count: int,
        ) -> pd.DataFrame:
            calls.append((market, code, category, start, count))
            if len(calls) == 1:
                raise TdxDecodeError("day datetime: 数据不足")
            return pd.DataFrame(
                {
                    "date": [pd.Timestamp("2026-07-07")],
                    "open": [10.0],
                    "high": [10.5],
                    "low": [9.9],
                    "close": [10.2],
                    "vol": [100000.0],
                    "amount": [1000000.0],
                }
            )

        client.get_security_bars = fake_get_security_bars

        bars = _fetch_all_daily_bars(
            client, market=0, code="000001", need_full=False, is_index=False, max_retries=3
        )

        assert len(bars) == 1
        assert len(calls) == 2  # 第一次失败，第二次成功

    def test_raises_after_retries_exhausted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """单页失败且重试耗尽，应抛出带页码信息的异常。"""
        client = MagicMock()
        client.get_security_bars.side_effect = TdxDecodeError("day datetime: 数据不足")

        with pytest.raises(TdxDecodeError, match="第 1 页拉取失败.*重试 2 次"):
            _fetch_all_daily_bars(
                client, market=0, code="000001", need_full=False, is_index=False, max_retries=2
            )

        assert client.get_security_bars.call_count == 3  # 首次 + 2 次重试
