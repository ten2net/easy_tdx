"""sync-all --all-stocks 全市场同步测试（无网络）。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from click.testing import CliRunner

from easy_tdx.cli import cli


@pytest.fixture
def mock_security_list() -> pd.DataFrame:
    """模拟 get_security_list_all 返回的沪深 A 股列表。"""
    from easy_tdx.models.enums import Market

    return pd.DataFrame(
        {
            "market": [Market.SZ, Market.SH, Market.SZ],
            "code": ["000001", "600000", "000002"],
            "name": ["平安银行", "浦发银行", "万科A"],
        }
    )


class TestSyncAllStocks:
    def test_all_stocks_creates_missing_files(
        self, tmp_path: Path, mock_security_list: pd.DataFrame
    ) -> None:
        """--all-stocks 应为服务端有但本地无的股票创建 .day 文件。"""
        sync_log: list[Path] = []

        def fake_sync_one_daily(client: object, filepath: Path) -> tuple[int, str]:
            sync_log.append(filepath)
            # 返回写入条数，模拟新建文件写入历史数据
            return 100, "+100"

        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get_security_list_all.return_value = mock_security_list

        with patch("easy_tdx.client.TdxClient.from_best_host", return_value=client):
            with patch("easy_tdx.cli.cmd_offline._sync_one_daily", side_effect=fake_sync_one_daily):
                runner = CliRunner()
                result = runner.invoke(
                    cli,
                    ["offline", "sync-all", "--vipdoc", str(tmp_path), "--all-stocks"],
                )

        assert result.exit_code == 0, result.output
        assert len(sync_log) == 3
        # 三个文件都应被处理（本地原来不存在）
        for name in ("sz000001.day", "sh600000.day", "sz000002.day"):
            assert any(p.name.lower() == name for p in sync_log), f"{name} 未被同步"

    def test_all_stocks_includes_existing_files(
        self, tmp_path: Path, mock_security_list: pd.DataFrame
    ) -> None:
        """--all-stocks 应同时覆盖本地已存在的文件进行增量更新。"""
        # 预先创建其中一个文件
        existing = tmp_path / "sh" / "lday" / "sh600000.day"
        existing.parent.mkdir(parents=True, exist_ok=True)
        existing.write_bytes(b"")

        sync_log: list[Path] = []

        def fake_sync_one_daily(client: object, filepath: Path) -> tuple[int, str]:
            sync_log.append(filepath)
            return 0, "已是最新"

        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get_security_list_all.return_value = mock_security_list

        with patch("easy_tdx.client.TdxClient.from_best_host", return_value=client):
            with patch("easy_tdx.cli.cmd_offline._sync_one_daily", side_effect=fake_sync_one_daily):
                runner = CliRunner()
                result = runner.invoke(
                    cli,
                    ["offline", "sync-all", "--vipdoc", str(tmp_path), "--all-stocks"],
                )

        assert result.exit_code == 0, result.output
        assert len(sync_log) == 3
        # 已存在的文件也应在列表中
        assert any(p == existing for p in sync_log)

    def test_default_mode_only_syncs_existing_files(self, tmp_path: Path) -> None:
        """默认模式只同步本地已有的 .day 文件。"""
        existing = tmp_path / "sh" / "lday" / "sh600000.day"
        existing.parent.mkdir(parents=True, exist_ok=True)
        existing.write_bytes(b"")

        sync_log: list[Path] = []

        def fake_sync_one_daily(client: object, filepath: Path) -> tuple[int, str]:
            sync_log.append(filepath)
            return 0, "已是最新"

        client = MagicMock()

        with patch("easy_tdx.client.TdxClient.from_best_host", return_value=client):
            with patch("easy_tdx.cli.cmd_offline._sync_one_daily", side_effect=fake_sync_one_daily):
                runner = CliRunner()
                result = runner.invoke(
                    cli,
                    ["offline", "sync-all", "--vipdoc", str(tmp_path)],
                )

        assert result.exit_code == 0, result.output
        assert len(sync_log) == 1
        assert sync_log[0] == existing
        # 默认模式不应调用全市场列表接口
        client.get_security_list_all.assert_not_called()

    def test_peer_and_all_stocks_are_mutually_exclusive(self) -> None:
        """--peer 与 --all-stocks 不能同时使用。"""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["offline", "sync-all", "--peer", "C:\\new_tdx\\vipdoc", "--all-stocks"],
        )
        assert result.exit_code != 0
        assert "不能同时使用" in result.output
