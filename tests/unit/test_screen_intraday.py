"""screen intraday 分钟线异动扫描单元测试。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from easy_tdx.models.bar import SecurityBar
from easy_tdx.screen.intraday import IntradayResult, IntradayScanner


def _make_bar(
    dt: datetime,
    open_price: float,
    close: float,
    high: float,
    low: float,
    vol: float,
    amount: float,
) -> SecurityBar:
    """快速构造一个 SecurityBar。"""
    return SecurityBar(
        open=open_price,
        close=close,
        high=high,
        low=low,
        vol=vol,
        amount=amount,
        year=dt.year,
        month=dt.month,
        day=dt.day,
        hour=dt.hour,
        minute=dt.minute,
    )


def _make_bars(
    n: int,
    base_close: float = 10.0,
    vol_base: float = 1000.0,
    surge_at_end: bool = False,
) -> list[SecurityBar]:
    """构造 n 根连续 5 分钟 K 线。

    surge_at_end=True 时最后 6 根大幅拉升并放量。
    """
    bars: list[SecurityBar] = []
    dt = datetime(2024, 6, 24, 9, 35)
    close = base_close
    for i in range(n):
        if surge_at_end and i >= n - 6:
            close *= 1.005  # 最后 6 根每根涨 0.5%
            vol = vol_base * 3.0
        else:
            close *= 1.0002  # 正常微涨
            vol = vol_base
        high = close * 1.001
        low = close * 0.999
        bars.append(
            _make_bar(
                dt,
                open_price=close * 0.9998,
                close=close,
                high=high,
                low=low,
                vol=vol,
                amount=close * vol,
            )
        )
        dt += timedelta(minutes=5)
    return bars


def _sample_result() -> IntradayResult:
    """返回一个用于输出格式测试的 IntradayResult。"""
    return IntradayResult(
        rank=1,
        code="000001",
        market="SZ",
        last_close=12.5,
        last_time="2024-06-24 10:00",
        pct_n=0.03,
        volume_ratio=2.5,
        score=0.04,
    )


class TestIntradayScanner:
    """测试 IntradayScanner 核心逻辑。"""

    def test_detect_surge(self, tmp_path: Path) -> None:
        """能正确识别最后 6 根放量拉升的异动。"""
        scanner = IntradayScanner(
            vipdoc_path=tmp_path,
            period="5MIN",
            lookback=6,
            min_pct=2.0,
            volume_ratio=1.5,
        )

        bars = _make_bars(50, base_close=10.0, surge_at_end=True)
        with patch.object(scanner, "_read_bars", return_value=bars):
            result = scanner._compute_one(Path("/fake/sh600000.5"), "SH", "600000")

        assert result is not None
        assert result.market == "SH"
        assert result.code == "600000"
        assert result.pct_n > 0.02
        assert result.volume_ratio > 1.5

    def test_no_surge_filtered(self, tmp_path: Path) -> None:
        """不满足涨幅/量比条件时不触发。"""
        scanner = IntradayScanner(
            vipdoc_path=tmp_path,
            period="5MIN",
            lookback=6,
            min_pct=2.0,
            volume_ratio=1.5,
        )

        bars = _make_bars(50, base_close=10.0, surge_at_end=False)
        with patch.object(scanner, "_read_bars", return_value=bars):
            result = scanner._compute_one(Path("/fake/sh600000.5"), "SH", "600000")

        assert result is None

    def test_min_bars_not_enough(self, tmp_path: Path) -> None:
        """数据条数不足时跳过。"""
        scanner = IntradayScanner(
            vipdoc_path=tmp_path,
            period="5MIN",
            lookback=6,
            min_pct=2.0,
            volume_ratio=1.5,
        )

        bars = _make_bars(10, base_close=10.0)
        with patch.object(scanner, "_read_bars", return_value=bars):
            result = scanner._compute_one(Path("/fake/sh600000.5"), "SH", "600000")

        assert result is None

    def test_breakout_detection(self, tmp_path: Path) -> None:
        """突破近期高点时应记录 breakout_high。"""
        scanner = IntradayScanner(
            vipdoc_path=tmp_path,
            period="5MIN",
            lookback=3,
            min_pct=1.0,
            volume_ratio=0.0,
            breakout_lookback=12,
        )

        bars = _make_bars(50, base_close=10.0, surge_at_end=True)
        with patch.object(scanner, "_read_bars", return_value=bars):
            result = scanner._compute_one(Path("/fake/sh600000.5"), "SH", "600000")

        assert result is not None
        assert result.breakout_high is not None

    def test_to_json(self) -> None:
        """JSON 输出包含必要字段。"""
        results = [_sample_result()]
        json_str = IntradayScanner.to_json(results, "5MIN")
        data = json.loads(json_str)

        assert data["period"] == "5MIN"
        assert data["total"] == 1
        assert data["ranking"][0]["code"] == "000001"

    def test_to_table(self) -> None:
        """表格输出不为空且包含标题。"""
        results = [_sample_result()]
        table = IntradayScanner.to_table(results, "5MIN")
        assert "分钟线异动扫描" in table
        assert "SZ000001" in table

    def test_invalid_period(self, tmp_path: Path) -> None:
        """不支持周期应抛 ValueError。"""
        with pytest.raises(ValueError, match="不支持周期"):
            IntradayScanner(vipdoc_path=tmp_path, period="15MIN")
