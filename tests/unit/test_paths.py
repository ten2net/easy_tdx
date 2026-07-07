"""离线路径解析测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from easy_tdx.exceptions import TdxOfflineError
from easy_tdx.offline.daily_bar import find_daily_bar_file
from easy_tdx.offline.paths import resolve_vipdoc


class TestResolveVipdoc:
    """resolve_vipdoc 行为测试。"""

    def test_existing_path_returned(self, tmp_path: Path) -> None:
        vipdoc = tmp_path / "vipdoc"
        vipdoc.mkdir()
        assert resolve_vipdoc(vipdoc) == vipdoc

    def test_missing_path_raises_without_create(self, tmp_path: Path) -> None:
        missing = tmp_path / "not_exist" / "vipdoc"
        with pytest.raises(TdxOfflineError, match="指定的 vipdoc 路径不存在"):
            resolve_vipdoc(missing)

    def test_missing_path_created_with_create(self, tmp_path: Path) -> None:
        missing = tmp_path / "not_exist" / "vipdoc"
        assert not missing.exists()
        result = resolve_vipdoc(missing, create=True)
        assert result == missing
        assert result.is_dir()


class TestFindDailyBarFile:
    """find_daily_bar_file 行为测试。"""

    def test_find_existing_vipdoc(self, tmp_path: Path) -> None:
        vipdoc = tmp_path / "vipdoc"
        vipdoc.mkdir()
        filepath = find_daily_bar_file(0, "000001", vipdoc)
        assert filepath == vipdoc / "sz" / "lday" / "sz000001.day"

    def test_find_missing_vipdoc_raises_without_create(self, tmp_path: Path) -> None:
        missing = tmp_path / "not_exist" / "vipdoc"
        with pytest.raises(TdxOfflineError, match="指定的 vipdoc 路径不存在"):
            find_daily_bar_file(0, "000001", missing)

    def test_find_missing_vipdoc_creates_dirs_with_create(self, tmp_path: Path) -> None:
        missing = tmp_path / "not_exist" / "vipdoc"
        filepath = find_daily_bar_file(0, "000001", missing, create=True)
        assert filepath == missing / "sz" / "lday" / "sz000001.day"
        assert filepath.parent.is_dir()
