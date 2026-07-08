"""screen CLI 写入板块单元测试（无需真实 .day 数据）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from easy_tdx.screen.cli import screen

_STRENGTH_PATH = "easy_tdx.screen.strength.StrengthRanker"
_SCANNER_PATH = "easy_tdx.screen.scanner.SignalScanner"


def _make_strength_result(rank: int, market: str, code: str, strength: float) -> Any:
    """构造一个 StrengthResult 风格的简单对象。"""
    r = MagicMock()
    r.rank = rank
    r.market = market
    r.code = code
    r.name = ""
    r.last_close = 10.0
    r.last_date = 20260624
    r.ret_5 = 0.01
    r.ret_20 = 0.05
    r.ret_60 = 0.10
    r.vol_20 = 0.02
    r.strength = strength
    return r


def _make_scan_result(market: str, code: str) -> Any:
    """构造一个 ScanResult 风格的简单对象。"""
    r = MagicMock()
    r.market = market
    r.code = code
    r.signal_date = 20260624
    r.last_close = 10.0
    return r


class TestStrengthCliToBlock:
    """测试 strength 命令的 --to-block 写入板块功能。"""

    def _mock_ranker(self) -> MagicMock:
        """构造一个返回固定结果的 mock StrengthRanker。"""
        mock_ranker_cls = MagicMock()
        mock_ranker = mock_ranker_cls.return_value
        mock_ranker.rank.return_value = [
            _make_strength_result(1, "SH", "600000", 9.5),
            _make_strength_result(2, "SZ", "000001", 6.2),
        ]
        return mock_ranker_cls

    def test_to_block_without_block_dir_fails(self) -> None:
        """只给 --to-block 不给 --block-dir 应报错退出。"""
        runner = CliRunner()
        with patch(_STRENGTH_PATH, self._mock_ranker()):
            result = runner.invoke(screen, ["strength", "--to-block", "强势股"])

        assert result.exit_code == 1
        assert "--block-dir" in result.output or "block-dir" in result.output

    def test_to_block_writes_block(self, tmp_path: Path) -> None:
        """--to-block + --block-dir 应正确写入通达信自定义板块。"""
        block_dir = tmp_path / "blocknew"
        block_dir.mkdir()
        (block_dir / "blocknew.cfg").write_bytes(b"")

        runner = CliRunner()
        with patch(_STRENGTH_PATH, self._mock_ranker()):
            result = runner.invoke(
                screen,
                [
                    "strength",
                    "--to-block",
                    "强势股",
                    "--block-dir",
                    str(block_dir),
                    "--top",
                    "2",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "已覆盖写入板块" in result.output

        # 验证 .blk 文件内容
        blk_files = list(block_dir.glob("*.blk"))
        assert len(blk_files) == 1
        lines = blk_files[0].read_text(encoding="utf-8").strip().splitlines()
        assert set(lines) == {"1600000", "0000001"}

        # 验证 blocknew.cfg 已注册
        cfg_data = (block_dir / "blocknew.cfg").read_bytes()
        assert cfg_data, "blocknew.cfg 应被写入"

    def test_to_block_append_mode(self, tmp_path: Path) -> None:
        """--block-mode append 应追加而非覆盖。"""
        block_dir = tmp_path / "blocknew"
        block_dir.mkdir()
        (block_dir / "blocknew.cfg").write_bytes(b"")

        runner = CliRunner()
        # 第一次写入一只股票
        with patch(_STRENGTH_PATH, self._mock_ranker_one("SH", "600000")):
            runner.invoke(
                screen,
                ["strength", "--to-block", "test", "--block-dir", str(block_dir)],
            )

        # 第二次追加另一只
        with patch(_STRENGTH_PATH, self._mock_ranker_one("SZ", "000001")):
            result = runner.invoke(
                screen,
                [
                    "strength",
                    "--to-block",
                    "test",
                    "--block-dir",
                    str(block_dir),
                    "--block-mode",
                    "append",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "已追加写入板块" in result.output

        blk_files = list(block_dir.glob("*.blk"))
        lines = blk_files[0].read_text(encoding="utf-8").strip().splitlines()
        assert lines == ["1600000", "0000001"]

    def _mock_ranker_one(self, market: str, code: str) -> MagicMock:
        """返回只包含一只股票的 mock StrengthRanker 类。"""
        mock_ranker_cls = MagicMock()
        mock_ranker = mock_ranker_cls.return_value
        mock_ranker.rank.return_value = [_make_strength_result(1, market, code, 1.0)]
        return mock_ranker_cls


class TestScanCliToBlock:
    """测试 screen scan 命令的 --to-block 写入板块功能。"""

    def _mock_scanner(self) -> MagicMock:
        """构造一个返回固定信号的 mock SignalScanner。"""
        mock_scanner_cls = MagicMock()
        mock_scanner = mock_scanner_cls.return_value
        mock_scanner.scan.return_value = [
            _make_scan_result("SH", "600000"),
            _make_scan_result("SZ", "000001"),
        ]
        mock_scanner.to_json.return_value = "{}"
        return mock_scanner_cls

    def test_scan_to_block_writes_block(self, tmp_path: Path) -> None:
        """scan --to-block 应把信号股票写入板块。"""
        block_dir = tmp_path / "blocknew"
        block_dir.mkdir()
        (block_dir / "blocknew.cfg").write_bytes(b"")

        strategy_file = tmp_path / "dummy_strategy.py"
        strategy_file.write_text(
            "from easy_tdx.backtest import Strategy\n"
            "class DummyStrategy(Strategy):\n"
            "    def init(self): pass\n"
            "    def next(self): pass\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        with patch(_SCANNER_PATH, self._mock_scanner()):
            result = runner.invoke(
                screen,
                [
                    "scan",
                    "--strategy",
                    str(strategy_file),
                    "--to-block",
                    "捉妖信号",
                    "--block-dir",
                    str(block_dir),
                ],
            )

        assert result.exit_code == 0, result.output
        assert "已覆盖写入板块" in result.output

        blk_files = list(block_dir.glob("*.blk"))
        assert len(blk_files) == 1
        lines = blk_files[0].read_text(encoding="utf-8").strip().splitlines()
        assert set(lines) == {"1600000", "0000001"}

    def test_scan_to_block_without_block_dir_fails(self, tmp_path: Path) -> None:
        """scan 只给 --to-block 不给 --block-dir 应报错退出。"""
        strategy_file = tmp_path / "dummy_strategy.py"
        strategy_file.write_text(
            "from easy_tdx.backtest import Strategy\n"
            "class DummyStrategy(Strategy):\n"
            "    def init(self): pass\n"
            "    def next(self): pass\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        with patch(_SCANNER_PATH, self._mock_scanner()):
            result = runner.invoke(
                screen,
                ["scan", "--strategy", str(strategy_file), "--to-block", "test"],
            )

        assert result.exit_code == 1
        assert "--block-dir" in result.output or "block-dir" in result.output
