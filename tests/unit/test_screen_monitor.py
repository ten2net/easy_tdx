"""screen monitor 在线分钟线监控单元测试。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from easy_tdx.screen.monitor import IntradayMonitor, MonitorResult


def _make_kline(n: int, surge_at_end: bool = False) -> pd.DataFrame:
    """构造 n 根连续 5 分钟 K 线 DataFrame。"""
    rows = []
    dt = datetime(2024, 6, 24, 9, 35)
    close = 10.0
    for i in range(n):
        if surge_at_end and i >= n - 3:
            close *= 1.006
            vol = 3000.0
        else:
            close *= 1.0001
            vol = 1000.0
        open_p = close * 0.9999
        high = close * 1.001
        low = close * 0.999
        rows.append(
            {
                "datetime": dt,
                "open": open_p,
                "close": close,
                "high": high,
                "low": low,
                "vol": vol,
                "amount": close * vol,
            }
        )
        dt += timedelta(minutes=5)
    return pd.DataFrame(rows)


def _patch_mac_client(kline_df: pd.DataFrame) -> Any:
    """构造一个返回固定 K 线数据的 mock MacClient 类。"""
    mock_client_cls = MagicMock()
    mock_client = mock_client_cls.from_best_host.return_value
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get_stock_kline.return_value = kline_df
    return mock_client_cls


class TestIntradayMonitor:
    """测试 IntradayMonitor 核心逻辑。"""

    def test_detect_surge(self) -> None:
        """能正确识别最后 3 根放量拉升的异动。"""
        monitor = IntradayMonitor(
            period="5MIN",
            lookback=3,
            min_pct=1.0,
            volume_ratio=1.5,
        )

        df = _make_kline(30, surge_at_end=True)
        with patch("easy_tdx.mac.client.MacClient", _patch_mac_client(df)):
            result = monitor._compute_one("SH", "600000")

        assert result is not None
        assert result.market == "SH"
        assert result.code == "600000"
        assert result.pct_n > 0.01
        assert result.volume_ratio > 1.5

    def test_no_surge_filtered(self) -> None:
        """不满足涨幅/量比条件时不触发。"""
        monitor = IntradayMonitor(
            period="5MIN",
            lookback=3,
            min_pct=1.0,
            volume_ratio=1.5,
        )

        df = _make_kline(30, surge_at_end=False)
        with patch("easy_tdx.mac.client.MacClient", _patch_mac_client(df)):
            result = monitor._compute_one("SH", "600000")

        assert result is None

    def test_scan_empty_codes(self) -> None:
        """空股票池返回空列表。"""
        monitor = IntradayMonitor()
        assert monitor.scan([]) == []

    def test_scan_with_progress(self) -> None:
        """scan 正常返回并按 score 排序。"""
        monitor = IntradayMonitor(
            period="5MIN",
            lookback=3,
            min_pct=0.5,
            volume_ratio=0.0,
        )

        # 第一只大涨，第二只微涨
        df1 = _make_kline(30, surge_at_end=True)
        df2 = _make_kline(30, surge_at_end=False)

        calls: dict[str, pd.DataFrame] = {
            ("SH", "600000"): df1,
            ("SZ", "000001"): df2,
        }

        def side_effect(mkt: int, code: str, **kwargs: Any) -> pd.DataFrame:
            key = ("SH" if mkt == 1 else "SZ", code)
            return calls[key]

        mock_client_cls = MagicMock()
        mock_client = mock_client_cls.from_best_host.return_value
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get_stock_kline.side_effect = side_effect

        with patch("easy_tdx.mac.client.MacClient", mock_client_cls):
            results = monitor.scan([("SH", "600000"), ("SZ", "000001")], workers=0)

        assert len(results) == 1
        assert results[0].code == "600000"
        assert results[0].rank == 1

    def test_to_json(self) -> None:
        """JSON 输出包含必要字段。"""
        results = [
            MonitorResult(
                rank=1,
                code="000001",
                market="SZ",
                name="平安银行",
                last_close=12.5,
                last_time="2024-06-24 10:00",
                pct_n=0.02,
                volume_ratio=2.0,
                score=0.03,
            )
        ]
        json_str = IntradayMonitor.to_json(results, "5MIN")
        data = json.loads(json_str)

        assert data["period"] == "5MIN"
        assert data["total"] == 1
        assert data["ranking"][0]["code"] == "000001"
        assert data["ranking"][0]["name"] == "平安银行"

    def test_to_table(self) -> None:
        """表格输出不为空且包含标题。"""
        results = [
            MonitorResult(
                rank=1,
                code="000001",
                market="SZ",
                name="平安银行",
                last_close=12.5,
                last_time="2024-06-24 10:00",
                pct_n=0.02,
                volume_ratio=2.0,
                score=0.03,
            )
        ]
        table = IntradayMonitor.to_table(results, "5MIN")
        assert "在线分钟线监控" in table
        assert "SZ000001" in table

    def test_invalid_period(self) -> None:
        """不支持周期应抛 ValueError。"""
        with pytest.raises(ValueError, match="不支持周期"):
            IntradayMonitor(period="15MIN")
